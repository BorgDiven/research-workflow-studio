"""Optional reading-PDF derivation; preserves page content and original files."""

import base64
from io import BytesIO
from pathlib import Path
import re
import zlib


MAX_SOURCE_BYTES = 512 * 1024 * 1024
SMALL_PDF_MAX_BYTES = 8 * 1024 * 1024
MAX_PAGES = 1000
MAX_IMAGES = 10000
MAX_IMAGE_PIXELS = 25_000_000
MAX_TOTAL_PIXELS = 2_000_000_000
MAX_IMAGE_BYTES = 80 * 1024 * 1024
MAX_PAGE_CONTENT_BYTES = 64 * 1024 * 1024
MAX_TOTAL_CONTENT_BYTES = 1024 * 1024 * 1024
JPEG_QUALITY = 90


class _LimitedOutput:
    def __init__(self, stream, limit):
        self.stream, self.limit = stream, limit

    def write(self, data):
        if self.stream.tell() + len(data) > self.limit:
            raise ValueError('PDF reading output exceeds its size limit; no original fallback is served.')
        return self.stream.write(data)

    def __getattr__(self, name):
        return getattr(self.stream, name)


def pdf_converter_available():
    try:
        import pypdf  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        return False
    return True


def _object(value):
    return value.get_object() if hasattr(value, 'get_object') else value


def _images(resources, seen_resources, seen_images, depth=0):
    """Walk image/form resources without decoding unsupported raster content."""
    if depth > 32:
        raise ValueError('PDF resource nesting exceeds the reading limit.')
    resources = _object(resources)
    if not resources or id(resources) in seen_resources:
        return
    seen_resources.add(id(resources))
    if len(seen_resources) > 20000:
        raise ValueError('PDF resource count exceeds the reading limit.')
    objects = _object(resources.get('/XObject', {}))
    for reference in objects.values():
        item = _object(reference)
        if item.get('/Subtype') == '/Form':
            yield from _images(item.get('/Resources'), seen_resources, seen_images, depth + 1)
        elif item.get('/Subtype') == '/Image' and id(item) not in seen_images:
            seen_images.add(id(item))
            if len(seen_images) > MAX_IMAGES:
                raise ValueError('PDF image count exceeds the reading limit.')
            yield item


def _pixels(image, width, height, channels):
    """Decode only supported bounded streams, never an unrestricted PDF filter."""
    filters = _object(image.get('/Filter', []))
    if isinstance(filters, str):
        filters = [filters]
    if list(filters) not in ([], ['/FlateDecode'], ['/ASCII85Decode', '/FlateDecode']):
        return None
    parameters = _object(image.get('/DecodeParms'))
    if isinstance(parameters, list):
        parameters = _object(parameters[-1]) if parameters else None
    if parameters is not None and hasattr(parameters, 'get') and parameters.get('/Predictor', 1) != 1:
        return None
    # _data is the encoded stream. get_data() would apply an unbounded decoder.
    data = image._data
    if len(data) > MAX_IMAGE_BYTES:
        return None
    if filters and filters[0] == '/ASCII85Decode':
        data = data.strip()
        adobe = data.endswith(b'~>')
        if adobe and not data.startswith(b'<~'):
            data = b'<~' + data
        data = base64.a85decode(data, adobe=adobe)
    expected = width * height * channels
    if filters and filters[-1] == '/FlateDecode':
        decoder = zlib.decompressobj()
        data = decoder.decompress(data, expected + 1)
        if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            return None
    return data if len(data) == expected else None


def _page_content(page):
    """Bound decoding before asking the PDF parser to inspect inline images."""
    contents = _object(page.get('/Contents'))
    if contents is None:
        return b''
    streams = contents if isinstance(contents, list) else [contents]
    chunks, total = [], 0
    for reference in streams:
        stream = _object(reference)
        filters = _object(stream.get('/Filter', []))
        if isinstance(filters, str):
            filters = [filters]
        if list(filters) not in ([], ['/FlateDecode'], ['/ASCII85Decode', '/FlateDecode']):
            return None
        parameters = _object(stream.get('/DecodeParms'))
        parameters = parameters if isinstance(parameters, list) else [parameters]
        if any(hasattr(_object(item), 'get') and _object(item).get('/Predictor', 1) != 1
               for item in parameters):
            return None
        data = stream._data
        if len(data) > MAX_PAGE_CONTENT_BYTES:
            raise ValueError('PDF page content exceeds the 64 MiB reading limit.')
        if filters and filters[0] == '/ASCII85Decode':
            data = data.strip()
            adobe = data.endswith(b'~>')
            if adobe and not data.startswith(b'<~'):
                data = b'<~' + data
            data = base64.a85decode(data, adobe=adobe)
        if filters and filters[-1] == '/FlateDecode':
            decoder = zlib.decompressobj()
            data = decoder.decompress(data, MAX_PAGE_CONTENT_BYTES - total + 1)
            if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                raise ValueError('PDF page content is invalid or exceeds the reading limit.')
        total += len(data) + 1
        if total > MAX_PAGE_CONTENT_BYTES:
            raise ValueError('PDF page content exceeds the 64 MiB reading limit.')
        chunks.append(data)
    return b'\n'.join(chunks)


def _inline_image(operands):
    """Normalize only PDF inline aliases; preserve the actual original settings."""
    from pypdf.generic import ArrayObject, EncodedStreamObject, NameObject
    aliases = {'/W': '/Width', '/H': '/Height', '/BPC': '/BitsPerComponent',
               '/CS': '/ColorSpace', '/F': '/Filter', '/DP': '/DecodeParms',
               '/IM': '/ImageMask', '/D': '/Decode'}
    colors = {'/RGB': '/DeviceRGB', '/G': '/DeviceGray', '/CMYK': '/DeviceCMYK'}
    filters = {'/A85': '/ASCII85Decode', '/Fl': '/FlateDecode', '/DCT': '/DCTDecode'}
    image = EncodedStreamObject()
    for key, value in operands['settings'].items():
        key = aliases.get(key, key)
        if key == '/ColorSpace' and isinstance(value, str):
            value = NameObject(colors.get(value, value))
        if key == '/Filter':
            values = value if isinstance(value, list) else [value]
            value = ArrayObject([NameObject(filters.get(item, item)) for item in values])
        image[NameObject(key)] = value
    image._data = operands['data']
    return image


def generate_reading_pdf(source, destination):
    """Write a smaller reading copy, or clone an already compact PDF.

    Only opaque DeviceRGB/DeviceGray 8-bit image streams are recompressed.
    Page content, vectors, dimensions, links and document structure are cloned.
    The caller owns atomic publication of the unique temporary destination.
    """
    if not pdf_converter_available():
        raise RuntimeError('PDF reading requires optional pypdf and Pillow.')
    from PIL import Image
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import ArrayObject, ContentStream, DecodedStreamObject, NameObject

    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve() or (destination.exists() and source.samefile(destination)):
        raise ValueError('The reading PDF destination must differ from its original.')
    if destination.exists():
        raise ValueError('The reading PDF destination must be a new temporary file.')
    original_bytes = source.stat().st_size
    if not 0 < original_bytes <= MAX_SOURCE_BYTES:
        raise ValueError('PDF exceeds the 512 MiB reading input limit.')
    replaced, skipped, total_pixels, created = 0, 0, 0, False
    inline_images, replaced_inline, inline_pages, content_bytes = 0, 0, 0, 0
    writer = None
    already_small = original_bytes <= SMALL_PDF_MAX_BYTES

    def compress_image(image):
        nonlocal skipped, total_pixels
        color = image.get('/ColorSpace')
        if (color not in ('/DeviceRGB', '/DeviceGray')
                or image.get('/BitsPerComponent') != 8
                or any(key in image for key in ('/SMask', '/Mask', '/Decode'))
                or image.get('/ImageMask')):
            skipped += 1
            return None
        width, height = int(image.get('/Width', 0)), int(image.get('/Height', 0))
        if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
            skipped += 1
            return None
        total_pixels += width * height
        if total_pixels > MAX_TOTAL_PIXELS:
            raise ValueError('PDF raster workload exceeds the reading limit.')
        try:
            raw = _pixels(image, width, height, 3 if color == '/DeviceRGB' else 1)
        except (ValueError, zlib.error):
            raw = None
        if raw is None:
            skipped += 1
            return None
        with Image.frombytes('RGB' if color == '/DeviceRGB' else 'L', (width, height), raw) as raster:
            output = BytesIO()
            raster.save(output, format='JPEG', quality=JPEG_QUALITY, subsampling=0)
        encoded = output.getvalue()
        if len(encoded) >= len(image._data):
            skipped += 1
            return None
        return encoded

    try:
        with source.open('rb') as stream:
            reader = PdfReader(stream, strict=False)
            if reader.is_encrypted:
                raise ValueError('Encrypted PDFs need a separately supplied reading copy.')
            pages = len(reader.pages)
            if not 0 < pages <= MAX_PAGES:
                raise ValueError('PDF exceeds the 1000-page reading limit.')
            writer = PdfWriter(clone_from=reader)
            seen_resources, seen_images = set(), set()
            for page in writer.pages:
                for image in _images(page.get('/Resources'), seen_resources, seen_images):
                    if len(seen_images) + inline_images > MAX_IMAGES:
                        raise ValueError('PDF image count exceeds the reading limit.')
                    encoded = compress_image(image)
                    if encoded is None:
                        continue
                    # Keep image geometry/resources. Replace only encoded pixels
                    # and filter metadata; page drawing commands stay untouched.
                    image._data = encoded
                    if hasattr(image, 'decoded_self'):
                        image.decoded_self = None
                    image[NameObject('/Filter')] = NameObject('/DCTDecode')
                    for key in ('/DecodeParms', '/Length'):
                        image.pop(key, None)
                    replaced += 1
                data = _page_content(page)
                if data is None:
                    continue
                content_bytes += len(data)
                if content_bytes > MAX_TOTAL_CONTENT_BYTES:
                    raise ValueError('PDF page decoding exceeds the total reading limit.')
                if not re.search(rb'(?<!\S)BI(?=\s)', data):
                    continue
                decoded = DecodedStreamObject()
                decoded.set_data(data)
                content = ContentStream(decoded, writer)
                changed = False
                for operands, operator in content.operations:
                    if operator != b'INLINE IMAGE':
                        continue
                    inline_images += 1
                    if len(seen_images) + inline_images > MAX_IMAGES:
                        raise ValueError('PDF image count exceeds the reading limit.')
                    encoded = compress_image(_inline_image(operands))
                    if encoded is None:
                        continue
                    # ASCII85 makes the EI delimiter unambiguous, including for
                    # parsers that do not inspect JPEG's own end marker.
                    wrapped = base64.a85encode(encoded) + b'~>\n'
                    if len(wrapped) >= len(operands['data']):
                        skipped += 1
                        continue
                    operands['data'] = wrapped
                    settings = operands['settings']
                    for key in ('/F', '/Filter', '/DP', '/DecodeParms'):
                        settings.pop(key, None)
                    settings[NameObject('/F')] = ArrayObject([NameObject('/A85'), NameObject('/DCT')])
                    replaced += 1
                    replaced_inline += 1
                    changed = True
                if changed:
                    inline_pages += 1
                    # flate_encode reads _data, not the parsed operations. Force
                    # serialization first or a parsed page would become blank.
                    content.get_data()
                    page.replace_contents(content.flate_encode())
            if not replaced and not already_small:
                raise ValueError('This PDF has no safely reducible images; supply a reading copy separately.')
            with destination.open('xb') as output:
                created = True
                writer.write(_LimitedOutput(output, SMALL_PDF_MAX_BYTES if already_small else original_bytes - 1))
        reading_bytes = destination.stat().st_size
        if reading_bytes >= original_bytes and not already_small:
            raise ValueError('This PDF did not become smaller; no original fallback is served.')
        return {'pages': pages, 'recompressedImages': replaced, 'skippedImages': skipped,
                'recompressedInlineImages': replaced_inline, 'inlinePages': inline_pages,
                'contentBytesExamined': content_bytes,
                'originalBytes': original_bytes, 'bytes': reading_bytes, 'quality': JPEG_QUALITY,
                'alreadyLightweight': already_small and (not replaced or reading_bytes >= original_bytes)}
    except Exception as exc:
        # This function created only its unique destination; originals are untouched.
        if created:
            destination.unlink(missing_ok=True)
        if isinstance(exc, (ValueError, RuntimeError, OSError)):
            raise
        raise ValueError('PDF reading conversion failed; the original is unchanged.') from exc
    finally:
        if writer is not None:
            writer.close()
