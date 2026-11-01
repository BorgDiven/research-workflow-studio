"""Managed originals and disposable reading renditions; never research records.

The cache indexes exact managed URIs, not latest artifact versions. It never
fetches remote URLs, modifies originals, or treats previews as evaluation data.
"""
import os
import re
import sqlite3
import threading
import time
import uuid
import warnings
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import unquote, urlsplit

MAX_IMAGE_BYTES = 256 * 1024 * 1024
MAX_IMAGE_PIXELS = 50_000_000
MAX_CACHE_ENTRIES = 16384
PREVIEW_EDGE = 1280
PREVIEW_QUALITY = 85
PROFILE = 'reading-1280-q85-v1'
CACHE_FILENAME = re.compile(r'^rws-preview-[a-f0-9]{32}\.(?:webp|pdf)$')


class PreviewError(Exception):
    def __init__(self, message, code='preview_unavailable', status=503):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


def _pillow():
    try:
        from PIL import Image, ImageOps
        return Image, ImageOps
    except ImportError:
        raise PreviewError('阅读图未生成；此环境未安装可选的 Pillow 图像转换组件。')


def managed_relative(uri):
    """Decode the same path as /materials, without granting filesystem access."""
    if not isinstance(uri, str) or len(uri) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in uri):
        raise PreviewError('材料地址无效。', 'not_found', 404)
    try:
        parsed = urlsplit(uri)
    except ValueError as exc:
        raise PreviewError('材料地址无效。', 'not_found', 404) from exc
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or not parsed.path.startswith('/materials/'):
        raise PreviewError('只接受已登记的受管材料地址。', 'not_found', 404)
    relative = unquote(parsed.path[len('/materials/'):])
    if not relative or '\\' in relative or any(ord(c) < 32 or ord(c) == 127 for c in relative) or any(
            not part or part.startswith('.') for part in relative.split('/')):
        raise PreviewError('材料地址无效。', 'not_found', 404)
    return relative


class MaterialStorage:
    def __init__(self, db_path, materials_root=None, preview_cache_root=None, preview_cache_mb=512):
        base = Path(db_path).expanduser().resolve().parent
        self.materials_root = Path(materials_root or base / 'materials').expanduser().resolve()
        self.cache_root = Path(preview_cache_root or base / 'cache' / 'previews').expanduser().resolve()
        if self.materials_root == self.cache_root or self.materials_root in self.cache_root.parents or self.cache_root in self.materials_root.parents:
            raise ValueError('Original material and preview cache directories must not overlap.')
        if isinstance(preview_cache_mb, bool) or not isinstance(preview_cache_mb, int) or not 1 <= preview_cache_mb <= 65536:
            raise ValueError('preview-cache-mb must be an integer between 1 and 65536.')
        self.limit_bytes = preview_cache_mb * 1024 * 1024
        self._lock = threading.RLock()

    def original(self, uri):
        relative = managed_relative(uri)
        # Recheck resolved containment on each access, including cached reads.
        try:
            root = self.materials_root.resolve()
            candidate = (root / relative).resolve()
        except (OSError, RuntimeError) as exc:
            raise PreviewError('材料路径不可读取。', 'not_found', 404) from exc
        if root != self.materials_root or root not in candidate.parents:
            raise PreviewError('材料路径不可读取。', 'not_found', 404)
        return relative, candidate

    def _cache_path(self, filename):
        if not CACHE_FILENAME.fullmatch(filename):
            raise PreviewError('阅读缓存索引无效。')
        path = self.cache_root / filename
        if path.is_symlink() or path.resolve().parent != self.cache_root:
            raise PreviewError('阅读缓存路径无效。')
        return path

    @contextmanager
    def _exclusive(self):
        if self.cache_root.resolve() != self.cache_root:
            raise PreviewError('阅读缓存目录已改变；请检查存储配置。')
        self.cache_root.mkdir(parents=True, exist_ok=True)
        # A separate SQLite writer lock serializes both processes while allowing
        # the cache index to commit ownership before an image is generated.
        mutex_path = self.cache_root / 'preview-lock.sqlite3'
        index = self.cache_root / 'preview-index.sqlite3'
        if mutex_path.is_symlink() or index.is_symlink():
            raise PreviewError('阅读缓存索引路径无效。')
        with self._lock:
            mutex = sqlite3.connect(str(mutex_path), timeout=30, isolation_level=None)
            conn = None
            try:
                mutex.execute('BEGIN IMMEDIATE')
                conn = sqlite3.connect(str(index), timeout=30, isolation_level=None)
                conn.row_factory = sqlite3.Row
                conn.execute('PRAGMA auto_vacuum=INCREMENTAL')
                conn.execute("""CREATE TABLE IF NOT EXISTS previews (
                    uri TEXT PRIMARY KEY, profile TEXT NOT NULL, filename TEXT NOT NULL,
                    source_size INTEGER, source_mtime INTEGER, bytes INTEGER NOT NULL,
                    width INTEGER, height INTEGER, accessed REAL NOT NULL, ready INTEGER NOT NULL)""")
                conn.execute('CREATE INDEX IF NOT EXISTS preview_lru ON previews(ready, accessed)')
                conn.execute('CREATE TABLE IF NOT EXISTS cache_config (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
                binding = conn.execute("SELECT value FROM cache_config WHERE key='originals_root'").fetchone()
                if not binding or binding['value'] != str(self.materials_root):
                    # Equal relative names, sizes and timestamps in another
                    # directory do not establish the same scientific source.
                    # An unbound older cache is also not sufficient provenance.
                    for row in conn.execute('SELECT * FROM previews').fetchall():
                        self._remove(conn, row)
                    conn.execute("INSERT OR REPLACE INTO cache_config VALUES ('originals_root', ?)",
                                 (str(self.materials_root),))
                yield conn
            except PreviewError:
                raise
            except (OSError, ValueError, sqlite3.Error) as exc:
                raise PreviewError('阅读缓存暂时不可用；未改为下载原件。') from exc
            finally:
                if conn is not None:
                    conn.close()
                mutex.rollback()
                mutex.close()

    def _remove(self, conn, row):
        path = self._cache_path(row['filename'])
        # Only files named in this derived cache index are candidates for removal.
        path.unlink(missing_ok=True)
        temporary = path.with_suffix('.tmp')
        if temporary.is_symlink():
            raise PreviewError('阅读缓存临时路径无效。')
        temporary.unlink(missing_ok=True)
        conn.execute('DELETE FROM previews WHERE uri=?', (row['uri'],))

    def _prune(self, conn, reserve=0, keep=None, reconcile=False):
        # Reclaim journaled incomplete encodings without touching every cached
        # file on each image read. Full disk reconciliation is an explicit CLI
        # prune operation; the requested file is checked in preview() itself.
        for row in conn.execute('SELECT * FROM previews WHERE ready=0').fetchall():
            if row['uri'] != keep:
                self._remove(conn, row)
        if reconcile:
            for row in conn.execute('SELECT * FROM previews WHERE ready=1').fetchall():
                if row['uri'] != keep and not self._cache_path(row['filename']).is_file():
                    self._remove(conn, row)
        totals = conn.execute('SELECT COUNT(*) AS count, COALESCE(SUM(bytes),0) AS bytes FROM previews').fetchone()
        total, count = totals['bytes'], totals['count']
        while total + reserve > self.limit_bytes or count > MAX_CACHE_ENTRIES:
            rows = conn.execute('''SELECT * FROM previews WHERE ready=1
                                   AND (? IS NULL OR uri != ?)
                                   ORDER BY accessed ASC LIMIT 64''', (keep, keep)).fetchall()
            if not rows:
                break
            for row in rows:
                if total + reserve <= self.limit_bytes and count <= MAX_CACHE_ENTRIES:
                    break
                self._remove(conn, row)
                total -= row['bytes']
                count -= 1
        return total

    @staticmethod
    def _convert(source, destination):
        Image, ImageOps = _pillow()
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(source) as image:
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise PreviewError('图像超过阅读转换的像素上限；请提供较小的阅读材料。')
                if image.mode == 'F' or image.mode.startswith('I'):
                    raise PreviewError('高位深或浮点图像尚未指定显示范围；请登记明确转换的 8 位阅读图。')
                if getattr(image, 'is_animated', False):
                    raise PreviewError('动态图暂不转换为静态阅读图；请登记选定帧的阅读材料。')
                image = ImageOps.exif_transpose(image)
                resampling = getattr(Image, 'Resampling', Image)
                image.thumbnail((PREVIEW_EDGE, PREVIEW_EDGE), resampling.LANCZOS)
                alpha = image.mode in ('RGBA', 'LA') or 'transparency' in image.info
                image = image.convert('RGBA' if alpha else 'RGB')
                image.save(destination, format='WEBP', quality=PREVIEW_QUALITY, method=4)
                return image.size

    def preview(self, uri):
        """Return an open reading file and metadata; caller closes the stream.

        Open before releasing the lock so eviction cannot invalidate an active
        HTTP response. Pending file ownership is journaled before generation;
        interrupted writes can only be reclaimed through this cache index.
        """
        relative, source = self.original(uri)
        is_pdf = source.suffix.lower() == '.pdf'
        mime = 'application/pdf' if is_pdf else 'image/webp'
        with self._exclusive() as conn:
            self._prune(conn)
            row = conn.execute('SELECT * FROM previews WHERE uri=?', (relative,)).fetchone()
            available = source.is_file()
            stat = source.stat() if available else None
            valid = row and row['profile'] == PROFILE and self._cache_path(row['filename']).is_file()
            offline = not self.materials_root.is_dir()
            if valid and (offline or (stat and row['source_size'] == stat.st_size and row['source_mtime'] == stat.st_mtime_ns)):
                conn.execute('UPDATE previews SET accessed=? WHERE uri=?', (time.time(), relative))
                stream = self._cache_path(row['filename']).open('rb')
                return stream, {'bytes': row['bytes'], 'width': row['width'], 'height': row['height'], 'originalAvailable': available, 'mimeType': mime}
            if not stat:
                raise PreviewError('原始材料当前不可用，且没有可用的阅读缓存。')
            if stat.st_size > (512 * 1024 * 1024 if is_pdf else MAX_IMAGE_BYTES):
                raise PreviewError('图像文件超过阅读转换的大小上限；请提供较小的阅读材料。')
            if is_pdf:
                from .pdf_reading import generate_reading_pdf, pdf_converter_available
                if not pdf_converter_available():
                    raise PreviewError('阅读 PDF 未生成；此环境未安装可选的 PDF 转换组件。')
            else:
                _pillow()  # Fail explicitly before touching an existing cache.
            filename = 'rws-preview-' + uuid.uuid4().hex + ('.pdf' if is_pdf else '.webp')
            destination = self._cache_path(filename)
            temporary = destination.with_suffix('.tmp')
            if row:
                self._remove(conn, row)
            conn.execute('INSERT INTO previews VALUES (?,?,?,?,?,?,?,?,?,0)',
                         (relative, PROFILE, filename, stat.st_size, stat.st_mtime_ns, 0, 0, 0, time.time()))
            try:
                if is_pdf:
                    generate_reading_pdf(source, temporary)
                    width, height = None, None
                else:
                    width, height = self._convert(source, temporary)
                size = temporary.stat().st_size
                after = source.stat()
                if (stat.st_size, stat.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise PreviewError('原始材料正在更新；请稍后重新读取。')
                if size > self.limit_bytes:
                    raise PreviewError('单张阅读图超过缓存上限；请增大阅读缓存容量。')
                self._prune(conn, reserve=size, keep=relative)
                os.replace(temporary, destination)
                conn.execute('UPDATE previews SET bytes=?,width=?,height=?,ready=1 WHERE uri=?',
                             (size, width, height, relative))
                stream = destination.open('rb')
                return stream, {'bytes': size, 'width': width, 'height': height, 'originalAvailable': True, 'mimeType': mime}
            except Exception as exc:
                pending = conn.execute('SELECT * FROM previews WHERE uri=?', (relative,)).fetchone()
                if pending:
                    self._remove(conn, pending)
                if isinstance(exc, PreviewError):
                    raise
                raise PreviewError('阅读图暂时不可用；未改为下载原件。') from exc

    def status(self, prune=False):
        with self._exclusive() as conn:
            if prune:
                self._prune(conn, reconcile=True)
                conn.execute('PRAGMA incremental_vacuum')
            row = conn.execute('SELECT COUNT(*) AS count, COALESCE(SUM(bytes),0) AS bytes FROM previews WHERE ready=1').fetchone()
            try:
                _pillow()
                converter = True
            except PreviewError:
                converter = False
            from .pdf_reading import pdf_converter_available
            return {'previewCount': row['count'], 'previewBytes': row['bytes'],
                    'previewLimitBytes': self.limit_bytes, 'maxEntries': MAX_CACHE_ENTRIES,
                    'indexBytes': (self.cache_root / 'preview-index.sqlite3').stat().st_size,
                    'converterAvailable': converter, 'pdfConverterAvailable': pdf_converter_available(), 'originalsAvailable': self.materials_root.is_dir(),
                    'maxEdge': PREVIEW_EDGE, 'quality': PREVIEW_QUALITY}
