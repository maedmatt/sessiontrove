"""Read-only localhost viewer for archived sessions.

The server binds to 127.0.0.1 only and answers GET requests. Session
files are addressed by ids taken from the server's own archive scan, so
client input never reaches the filesystem and traversal is impossible.
"""

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import pi

READERS = {"pi": pi}

_STATIC = {
    "index.html": "text/html; charset=utf-8",
    "viewer.css": "text/css; charset=utf-8",
    "viewer.js": "text/javascript; charset=utf-8",
}
_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'self'; script-src 'self'; "
        "img-src 'self' data:; connect-src 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


class ViewerServer(ThreadingHTTPServer):
    """Serve one archive directory on 127.0.0.1."""

    def __init__(self, root: Path, port: int = 0) -> None:
        super().__init__(("127.0.0.1", port), _Handler)
        self.root = Path(root)
        self.paths: dict[str, tuple[str, Path]] = {}
        self.lock = threading.Lock()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/"

    def sessions(self) -> list[dict]:
        """Rescan the archive and return session summaries."""

        summaries = []
        paths = {}
        for agent, reader in READERS.items():
            for summary, path in reader.find(self.root):
                paths[summary["id"]] = (agent, path)
                summaries.append(summary)
        summaries.sort(key=lambda summary: summary.get("started") or "", reverse=True)
        with self.lock:
            self.paths = paths
        return summaries

    def lookup(self, session_id: str) -> tuple[str, Path] | None:
        with self.lock:
            known = session_id in self.paths
        if not known:
            self.sessions()
        with self.lock:
            return self.paths.get(session_id)


class _Handler(BaseHTTPRequestHandler):
    server: ViewerServer

    def log_message(self, format: str, *args) -> None:
        pass

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        try:
            if url.path == "/":
                self._static("index.html")
            elif url.path.startswith("/static/"):
                self._static(url.path.removeprefix("/static/"))
            elif url.path == "/api/sessions":
                self._json(self.server.sessions())
            elif url.path == "/api/session":
                self._session(parse_qs(url.query).get("id", [""])[0])
            else:
                self._error(404)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _session(self, session_id: str) -> None:
        entry = self.server.lookup(session_id)
        if entry is None:
            self._error(404)
            return
        agent, path = entry
        try:
            parsed = READERS[agent].parse(path)
        except OSError:
            self._error(404)
            return
        parsed["id"] = session_id
        self._json(parsed)

    def _static(self, name: str) -> None:
        content_type = _STATIC.get(name)
        if content_type is None:
            self._error(404)
            return
        data = files("sessiontrove").joinpath("static", name).read_bytes()
        self._send(200, content_type, data)

    def _json(self, payload) -> None:
        self._send(200, "application/json", json.dumps(payload).encode())

    def _error(self, code: int) -> None:
        self._send(code, "text/plain; charset=utf-8", b"not found")

    def _send(self, code: int, content_type: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in _SECURITY_HEADERS.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)


def serve(root: Path, port: int = 0, open_browser: bool = True) -> int:
    """Serve the archive until interrupted."""

    server = ViewerServer(root, port)
    print(f"viewing {server.root} at {server.url} (press Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(server.url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
