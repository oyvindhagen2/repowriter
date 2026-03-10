"""
preview.server — local Dev.to article preview with live reload.

Usage:
    from preview.server import serve
    serve("/path/to/articles", port=4242)
"""

from __future__ import annotations

import os
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn


class _ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle each request in a separate thread."""
    daemon_threads = True
from pathlib import Path

from preview.renderer import render
from preview.template import render_page

# ---------------------------------------------------------------------------
# SSE client registry
# ---------------------------------------------------------------------------

_sse_clients: list = []
_sse_lock = threading.Lock()


def _notify_clients() -> None:
    """Push a reload event to all connected SSE clients."""
    with _sse_lock:
        dead: list = []
        for wfile in _sse_clients:
            try:
                wfile.write(b"data: reload\n\n")
                wfile.flush()
            except OSError:
                dead.append(wfile)
        for wfile in dead:
            _sse_clients.remove(wfile)


# ---------------------------------------------------------------------------
# File watcher (polling, no external dependencies)
# ---------------------------------------------------------------------------

def _watch(directory: str, interval: float = 0.5) -> None:
    """Background thread: poll .md mtimes, fire SSE on change."""
    watched: dict[Path, float] = {}

    while True:
        changed = False
        root = Path(directory)
        current_files = set(root.glob("*.md"))

        for path in current_files:
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if path not in watched or watched[path] != mtime:
                watched[path] = mtime
                changed = True

        # Also detect deletions
        for path in set(watched) - current_files:
            del watched[path]
            changed = True

        if changed:
            _notify_clients()

        time.sleep(interval)


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

_RELOAD_JS = """
<script>
const es = new EventSource('/events');
es.onmessage = () => location.reload();
</script>
""".strip()

_PAGE_STYLE = """
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         max-width: 860px; margin: 40px auto; padding: 0 20px; color: #222; }
  a { color: #3b49df; text-decoration: none; }
  a:hover { text-decoration: underline; }
  h1 { font-size: 1.8rem; border-bottom: 2px solid #eee; padding-bottom: .4em; }
  li { margin: .4em 0; font-size: 1.05rem; }
</style>
""".strip()


def _html_page(title: str, body: str) -> bytes:
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  {_PAGE_STYLE}
</head>
<body>
{body}
{_RELOAD_JS}
</body>
</html>"""
    return html.encode("utf-8")


def _slug_from_filename(name: str) -> str:
    """article-01-my-title.md  →  article-01-my-title"""
    return Path(name).stem


def _filename_from_slug(slug: str, directory: str) -> Path | None:
    """article-01-my-title  →  Path('.../article-01-my-title.md')"""
    candidate = Path(directory) / f"{slug}.md"
    return candidate if candidate.exists() else None


# ---------------------------------------------------------------------------
# Request handler factory (needs directory in closure)
# ---------------------------------------------------------------------------

def _make_handler(directory: str):
    class _Handler(BaseHTTPRequestHandler):
        _directory = directory

        # silence default access log noise — swap for pass to go quiet
        def log_message(self, fmt, *args):
            pass  # comment out to enable access logs

        def do_GET(self):
            path = self.path.split("?")[0]  # strip query string

            if path == "/":
                self._serve_index()
            elif path == "/events":
                self._serve_sse()
            elif path.startswith("/article-"):
                slug = path.lstrip("/")
                self._serve_article(slug)
            else:
                self._send_404()

        # --- index ---

        def _serve_index(self):
            root = Path(self._directory)
            articles = sorted(root.glob("article-*.md"))

            if articles:
                items = "\n".join(
                    f'<li><a href="/{_slug_from_filename(p.name)}">'
                    f'{_slug_from_filename(p.name)}</a></li>'
                    for p in articles
                )
                body = f"<h1>Dev.to Preview</h1><ul>{items}</ul>"
            else:
                body = (
                    "<h1>Dev.to Preview</h1>"
                    "<p>No <code>article-*.md</code> files found in "
                    f"<code>{self._directory}</code>.</p>"
                )

            data = _html_page("Dev.to Preview", body)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        # --- article ---

        def _serve_article(self, slug: str):
            md_path = _filename_from_slug(slug, self._directory)
            if md_path is None:
                self._send_404()
                return

            source = md_path.read_text(encoding="utf-8")
            frontmatter, body_html = render(source)
            page = render_page(frontmatter, body_html, article_path=slug)
            data = page.encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        # --- SSE ---


        def _serve_sse(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            with _sse_lock:
                _sse_clients.append(self.wfile)

            # Keep the connection open until the client disconnects
            try:
                while True:
                    time.sleep(1)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                with _sse_lock:
                    if self.wfile in _sse_clients:
                        _sse_clients.remove(self.wfile)

        # --- 404 ---

        def _send_404(self):
            body = _html_page("Not Found", "<h1>404 — Not Found</h1>")
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return _Handler


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def serve(directory: str, port: int = 4242) -> None:
    """Start the preview server. Blocks until Ctrl+C."""
    directory = str(Path(directory).resolve())

    handler_cls = _make_handler(directory)
    server = _ThreadedHTTPServer(("127.0.0.1", port), handler_cls)

    # File watcher in background
    watcher = threading.Thread(target=_watch, args=(directory,), daemon=True)
    watcher.start()

    url = f"http://localhost:{port}"
    print(f"Dev.to Preview  →  {url}")
    print(f"Watching        →  {directory}")
    print("Press Ctrl+C to stop.\n")

    webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping preview server.")
    finally:
        server.shutdown()
