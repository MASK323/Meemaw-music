from __future__ import annotations

import hashlib
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MeemawMusic/1.0",
    "Referer": "http://www.kugou.com/",
    "Accept": "*/*",
    "Connection": "close",
}

_urls: Dict[str, List[str]] = {}
_urls_lock = threading.Lock()
_MAX_URLS = 256
_MAX_CANDIDATES = 4
_server: ThreadingHTTPServer | None = None
_server_lock = threading.Lock()


class _ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args) -> None:
        pass

    def do_HEAD(self) -> None:
        self._forward(send_body=False)

    def do_GET(self) -> None:
        self._forward(send_body=True)

    def _forward(self, send_body: bool) -> None:
        token = self.path.strip("/")
        with _urls_lock:
            targets = _urls.get(token) or []
        if not targets:
            self.send_error(404, "Unknown audio stream")
            return

        headers = dict(_HEADERS)
        if self.headers.get("Range"):
            headers["Range"] = self.headers.get("Range")

        upstream = None
        candidates = targets[:_MAX_CANDIDATES]
        for target in candidates:
            try:
                request = urllib.request.Request(target, headers=headers)
                candidate = urllib.request.urlopen(request, timeout=5)
                if 200 <= candidate.status < 300:
                    upstream = candidate
                    break
                candidate.close()
            except OSError:
                continue

        if upstream is None:
            try:
                self.send_response(502)
                self.send_header("Content-Length", "0")
                self.send_header("Connection", "close")
                self.end_headers()
            except Exception:
                pass
            return

        try:
            self.send_response(upstream.status)
            for key in (
                "Content-Type",
                "Content-Length",
                "Content-Range",
                "Accept-Ranges",
                "Cache-Control",
                "ETag",
                "Last-Modified",
            ):
                value = upstream.headers.get(key)
                if value:
                    self.send_header(key, value)
            self.send_header("Connection", "close")
            self.end_headers()

            if send_body:
                first_byte_deadline = time.monotonic() + 6.0
                while True:
                    if time.monotonic() > first_byte_deadline:
                        break
                    chunk = upstream.read(65536)
                    if not chunk:
                        break
                    first_byte_deadline = time.monotonic() + 8.0
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
            pass
        finally:
            try:
                upstream.close()
            except Exception:
                pass


def _ensure_server() -> ThreadingHTTPServer:
    global _server
    with _server_lock:
        if _server is None:
            _server = ThreadingHTTPServer(("127.0.0.1", 0), _ProxyHandler)
            _server.daemon_threads = True
            threading.Thread(target=_server.serve_forever, daemon=True).start()
        return _server


def proxy_url(url: str, fallbacks: Optional[List[str]] = None) -> str:
    token = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    targets = [url] + [candidate for candidate in (fallbacks or []) if candidate]
    with _urls_lock:
        _urls[token] = targets
        if len(_urls) > _MAX_URLS:
            _urls.pop(next(iter(_urls)))
    server = _ensure_server()
    return f"http://127.0.0.1:{server.server_port}/{token}"


def release_urls() -> None:
    """Drop resolved stream mappings immediately when the player exits."""
    with _urls_lock:
        _urls.clear()
