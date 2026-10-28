"""Local HTTP transport. All research writes go through the shared Store."""

import json
from importlib import metadata
import mimetypes
import re
import secrets
import shlex
import sys
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from . import __version__
from .core import RwsError, Store, tool_definitions
from .origin import normalize_web_origin


MAX_BODY_BYTES = 4 * 1024 * 1024
SESSION_SECONDS = 8 * 60 * 60
COOKIE_NAME = "rws_session"


def error_payload(code, message, details=None):
    error = {"code": code, "message": message}
    if details:
        error["details"] = details
    return {"ok": False, "error": error}


def error_status(code):
    if code == "storage_error":
        return 503
    if "conflict" in code or code in ("stale_revision", "stale_proposal"):
        return 409
    if code in ("approval_required", "session_expired", "forbidden", "permission_denied"):
        return 403
    if "not_found" in code:
        return 404
    return 400


def default_web_root():
    source = Path(__file__).resolve().parent.parent / "web"
    if (source / "index.html").is_file():
        return source
    # Wheel data follows the installation scheme, which can differ from
    # sys.prefix (for example pip --user). RECORD knows its exact location.
    try:
        distribution = metadata.distribution("research-workflow-studio")
        for resource in distribution.files or ():
            if resource.as_posix().endswith("share/research-workflow-studio/web/index.html"):
                index = Path(distribution.locate_file(resource)).resolve()
                if index.is_file():
                    return index.parent
    except (metadata.PackageNotFoundError, OSError):
        pass
    return Path(sys.prefix) / "share" / "research-workflow-studio" / "web"


class StudioHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, db_path, web_root=None, public_origin=None, tailscale_user=None):
        if address[0] not in ("127.0.0.1", "localhost"):
            raise ValueError("The local trial must bind to 127.0.0.1 or localhost.")
        if (public_origin is None) != (tailscale_user is None):
            raise ValueError("public_origin and tailscale_user must be configured together.")
        if tailscale_user is not None and (not isinstance(tailscale_user, str)
                or not tailscale_user or re.search(r"[\s\x00-\x1f\x7f]", tailscale_user)):
            raise ValueError("tailscale_user must be a nonempty Tailscale login name.")
        self.public_origin = normalize_web_origin(public_origin, allow_loopback=False) if public_origin is not None else None
        self.tailscale_user = tailscale_user
        self.store = Store(db_path)
        launcher = Path(__file__).resolve().parent.parent / "launch.py"
        prefix = [sys.executable, str(launcher)] if launcher.is_file() else [sys.executable, "-m", "rws"]
        self.operator_command_prefix = shlex.join(prefix + ["operate", "--db", str(Path(db_path).resolve())])
        self.web_root = Path(web_root or default_web_root()).resolve()
        self.material_root = Path(db_path).resolve().parent / "materials"
        self.sessions = {}
        self.session_lock = threading.Lock()
        super().__init__(address, StudioHandler)
        port = self.server_address[1]
        self.allowed_hosts = {"127.0.0.1:%s" % port, "localhost:%s" % port}
        if port == 80:
            self.allowed_hosts.update(("127.0.0.1", "localhost"))
        self.allowed_origins = {host: "http://" + host for host in self.allowed_hosts}
        if self.public_origin:
            self.allowed_origins[urlsplit(self.public_origin).netloc] = self.public_origin

    def issue_session(self):
        now = time.monotonic()
        with self.session_lock:
            self.sessions = {sid: value for sid, value in self.sessions.items()
                             if value[1] > now}
            if len(self.sessions) >= 512:
                oldest = min(self.sessions, key=lambda sid: self.sessions[sid][1])
                del self.sessions[oldest]
            session_id, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            self.sessions[session_id] = (csrf, now + SESSION_SECONDS)
        return session_id, csrf

    def valid_session(self, session_id, csrf):
        if not isinstance(csrf, str) or not csrf:
            return False
        with self.session_lock:
            found = self.sessions.get(session_id)
            return bool(found and found[1] > time.monotonic()
                        and secrets.compare_digest(found[0], csrf))


class StudioHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ResearchWorkflowStudio/" + __version__

    def log_message(self, message, *args):
        # Do not log request bodies, cookies, query strings or user data.
        pass

    def _send(self, status, body, content_type, headers=()):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; "
                         "style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; "
                         "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; "
                         "base-uri 'none'; form-action 'self'")
        for key, value in headers:
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status, value, headers=()):
        body = json.dumps(value, ensure_ascii=False, allow_nan=False,
                          separators=(",", ":")).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", headers)

    def _error(self, status, code, message, details=None):
        self._json(status, error_payload(code, message, details))

    def _allowed_request(self, require_origin=False):
        if len(self.headers.get_all("Host", [])) != 1 or any(
                len(self.headers.get_all(name, [])) > 1 for name in ("Origin", "Tailscale-User-Login")):
            self._error(403, "forbidden", "不接受重复或缺失的访问身份信息。")
            return False
        host = self.headers.get("Host", "").lower()
        self.request_origin = self.server.allowed_origins.get(host)
        if not self.request_origin:
            self._error(403, "forbidden", "不接受此 Host；请使用已配置的 Studio 地址。")
            return False
        if self.server.public_origin and self.request_origin != self.server.public_origin and any(
                name in self.headers for name in ("Tailscale-User-Login", "Tailscale-User-Name",
                    "Tailscale-User-Profile-Pic", "Forwarded", "X-Forwarded-For",
                    "X-Forwarded-Host", "X-Forwarded-Proto")):
            self._error(403, "forbidden", "代理访问必须使用已配置的远程 Studio 地址。")
            return False
        # Only the loopback-bound Serve proxy may supply the external identity.
        identity = self.headers.get("Tailscale-User-Login")
        if self.server.public_origin and (identity is not None or self.request_origin == self.server.public_origin) and identity != self.server.tailscale_user:
            self._error(403, "forbidden", "此 Tailscale 用户没有工作台访问权限。")
            return False
        origin = self.headers.get("Origin")
        if (require_origin and not origin) or (origin is not None and origin != self.request_origin):
            self._error(403, "forbidden", "仅允许同源页面提交此操作。")
            return False
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            self._error(403, "forbidden", "不接受跨站请求。")
            return False
        return True

    def _human_session(self):
        try:
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            morsel = cookies.get(COOKIE_NAME)
            sid = morsel.value if morsel else ""
        except Exception:
            sid = ""
        if not self.server.valid_session(sid, self.headers.get("X-RWS-CSRF", "")):
            self._error(403, "session_expired", "页面会话已失效；请更新会话后重试，当前输入应予保留。")
            return False
        return True

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._allowed_request():
            return
        parsed = urlsplit(self.path)
        try:
            if parsed.path == "/api/health":
                self._json(200, {"ok": True, "service": "Research Workflow Studio",
                                 "version": __version__, "mode": "local-single-user",
                                 "operatorCommandPrefix": self.server.operator_command_prefix})
            elif parsed.path == "/api/session":
                sid, csrf = self.server.issue_session()
                secure = "; Secure" if self.request_origin.startswith("https://") else ""
                self._json(200, {"ok": True, "csrfToken": csrf, "expiresIn": SESSION_SECONDS},
                           (("Set-Cookie", "%s=%s; Path=/; HttpOnly; SameSite=Strict; Max-Age=%s%s"
                             % (COOKIE_NAME, sid, SESSION_SECONDS, secure)),))
            elif parsed.path == "/api/state":
                params = parse_qs(parsed.query, keep_blank_values=True)
                if set(params) - {"projectId"} or len(params.get("projectId", [])) > 1:
                    self._error(400, "validation", "状态读取参数无效。")
                    return
                project_id = params.get("projectId", [None])[0]
                self._json(200, self.server.store.snapshot(project_id or None))
            elif parsed.path.startswith("/api/"):
                self._error(404, "not_found", "接口不存在。")
            elif parsed.path.startswith("/materials/"):
                self._material(parsed.path)
            else:
                self._static(parsed.path)
        except RwsError as exc:
            self._error(error_status(exc.code), exc.code, exc.message, exc.details)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self._error(500, "internal_error", "读取失败；未将结果标记为成功。")

    def _static(self, url_path):
        path = unquote(url_path)
        if "\x00" in path or "\\" in path:
            self._error(404, "not_found", "文件不存在。")
            return
        relative = path.lstrip("/") or "index.html"
        if any(part.startswith(".") for part in Path(relative).parts):
            self._error(404, "not_found", "文件不存在。")
            return
        candidate = (self.server.web_root / relative).resolve()
        if self.server.web_root not in candidate.parents or not candidate.is_file():
            self._error(404, "not_found", "文件不存在。")
            return
        content_type = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
            content_type += "; charset=utf-8"
        self._send(200, candidate.read_bytes(), content_type)

    def _material(self, url_path):
        """Serve only explicitly imported copies, never a supplied source path."""
        relative = unquote(url_path[len("/materials/"):])
        if not relative or "\x00" in relative or "\\" in relative or any(
                part.startswith(".") for part in Path(relative).parts):
            self._error(404, "not_found", "材料不存在。")
            return
        root = self.server.material_root.resolve()
        candidate = (root / relative).resolve()
        if root not in candidate.parents or not candidate.is_file():
            self._error(404, "not_found", "材料不存在。")
            return
        size = candidate.stat().st_size
        start, end, partial = 0, size - 1, False
        byte_range = self.headers.get("Range")
        if byte_range:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", byte_range)
            if not match or not any(match.groups()) or size == 0:
                self._send(416, b"", "application/octet-stream", (("Content-Range", "bytes */%s" % size),))
                return
            left, right = match.groups()
            if left:
                start = int(left)
                end = min(int(right), size - 1) if right else size - 1
            else:
                start = max(0, size - int(right))
            if start >= size or end < start:
                self._send(416, b"", "application/octet-stream", (("Content-Range", "bytes */%s" % size),))
                return
            partial = True
        media = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        safe_inline = media in {"image/png", "image/jpeg", "image/webp", "image/gif", "application/pdf", "text/plain"}
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", media if safe_inline else "application/octet-stream")
        self.send_header("Content-Length", str(max(0, end - start + 1)))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "private, max-age=3600")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; sandbox")
        self.send_header("Referrer-Policy", "no-referrer")
        if not safe_inline:
            self.send_header("Content-Disposition", "attachment")
        if partial:
            self.send_header("Content-Range", "bytes %s-%s/%s" % (start, end, size))
        self.end_headers()
        if self.command != "HEAD":
            with candidate.open("rb") as stream:
                stream.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = stream.read(min(256 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

    def do_POST(self):
        parsed = urlsplit(self.path)
        human = parsed.path == "/api/human/call"
        if not self._allowed_request(require_origin=human):
            self.close_connection = True
            return
        if parsed.path not in ("/api/call", "/api/human/call") or parsed.query:
            self._error(404, "not_found", "接口不存在。")
            self.close_connection = True
            return
        if human and not self._human_session():
            self.close_connection = True
            return
        if self.headers.get("Transfer-Encoding"):
            self._error(400, "validation", "不接受分块请求正文。")
            self.close_connection = True
            return
        if self.headers.get_content_type() != "application/json":
            self._error(415, "validation", "请求正文必须使用 application/json。")
            self.close_connection = True
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if not 0 < length <= MAX_BODY_BYTES:
            self._error(413 if length > MAX_BODY_BYTES else 400, "validation", "请求正文大小无效。")
            self.close_connection = True
            return
        try:
            self.connection.settimeout(10)
            data = self.rfile.read(length)
            if len(data) != length:
                raise ValueError("incomplete body")
            def reject_constant(value):
                raise ValueError("non-finite number")
            body = json.loads(data.decode("utf-8"), parse_constant=reject_constant)
            if not isinstance(body, dict) or set(body) != {"name", "arguments"}:
                raise ValueError("invalid envelope")
            if not isinstance(body["name"], str) or not isinstance(body["arguments"], dict):
                raise ValueError("invalid operation")
        except (UnicodeError, ValueError, TimeoutError):
            self._error(400, "validation", "无效 JSON 或操作参数。")
            self.close_connection = True
            return
        try:
            if body["name"] not in {tool["name"] for tool in tool_definitions()}:
                self._error(404, "not_found", "此操作不通过网页接口提供。")
                return
            result = self.server.store.call(body["name"], body["arguments"],
                                            actor="human" if human else "model")
            self._json(200, result)
        except RwsError as exc:
            self._error(error_status(exc.code), exc.code, exc.message, exc.details)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self._error(500, "internal_error", "操作未确认成功；请按原请求 ID 查询或重试。")

    def do_OPTIONS(self):
        self._error(405, "forbidden", "此本机服务不提供跨站 CORS 接口。")


def create_server(db_path, host="127.0.0.1", port=8831, web_root=None, public_origin=None, tailscale_user=None):
    return StudioHTTPServer((host, port), db_path, web_root, public_origin, tailscale_user)


def serve(db_path, host="127.0.0.1", port=8831, web_root=None, public_origin=None, tailscale_user=None):
    server = create_server(db_path, host, port, web_root, public_origin, tailscale_user)
    print("Research Workflow Studio: http://%s:%s/" % server.server_address, file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
