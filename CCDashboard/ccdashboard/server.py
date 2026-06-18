"""
server.py — CCDashboard local web server.

Serves the live dashboard (config inventory + conversation search/resume, and —
later — QuizMe) from a stdlib HTTP server bound to localhost only. The page is
rendered by ``build.render`` with a ``server_base`` so the browser knows it can
call the JSON API below.

Routes
------
GET  /                    -> the dashboard HTML (server mode)
GET  /api/config          -> the ~/.claude config view model (same as static)
GET  /api/conversations   -> all indexed conversations (metadata)
GET  /api/search?q=...    -> full-text conversation search results (+ snippets)
POST /api/resume          -> {"sessionId": "..."} opens an elevated PowerShell
                             that resumes that conversation in its working dir

Security: binds to 127.0.0.1 only; ``/api/resume`` resolves the working dir from
the indexed transcript (never the request) and validates the session id.
"""
from __future__ import annotations

import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ccdashboard import build, conversations, scan


def _make_handler(state: dict):
    class Handler(BaseHTTPRequestHandler):
        # -- helpers -----------------------------------------------------------
        def _send(self, code: int, body, ctype: str = "application/json") -> None:
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", f"{ctype}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _json(self, code: int, obj) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False))

        def log_message(self, *_args) -> None:  # keep the console quiet
            return

        # -- routes ------------------------------------------------------------
        def do_GET(self) -> None:
            route = urlparse(self.path)
            path = route.path
            if path in ("/", "/index.html"):
                html = build.render(state["view_model"], server_base=state["base"])
                self._send(200, html, "text/html")
            elif path == "/api/config":
                self._json(200, state["view_model"])
            elif path == "/api/conversations":
                self._json(200, {"conversations": [c.to_dict() for c in state["convos"]]})
            elif path == "/api/search":
                query = (parse_qs(route.query).get("q") or [""])[0]
                self._json(200, {"query": query, "results": conversations.search(state["convos"], query)})
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:
            route = urlparse(self.path)
            if route.path == "/api/resume":
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    payload = json.loads(self.rfile.read(length) or b"{}")
                    session_id = str(payload.get("sessionId", ""))
                    info = conversations.launch_resume(session_id, state["convos"])
                    self._json(200, {"ok": True, "cwd": info["cwd"]})
                except KeyError:
                    self._json(404, {"ok": False, "error": "unknown session id"})
                except Exception as exc:  # invalid id / launch failure
                    self._json(400, {"ok": False, "error": str(exc)})
            else:
                self._json(404, {"error": "not found"})

    return Handler


def serve(
    *,
    config_dir: Path,
    model: str = "claude-opus-4-8",
    host: str = "127.0.0.1",
    port: int = 0,
    open_browser: bool = True,
) -> None:
    """Index the config + conversations, then serve the live dashboard until Ctrl+C."""
    view_model = scan.build_view_model(config_dir)
    convos = conversations.index_conversations()

    httpd = ThreadingHTTPServer((host, port), _make_handler({}))
    actual_port = httpd.server_address[1]
    base = f"http://{host}:{actual_port}"
    # Rebuild the handler with full state now that we know the bound port.
    httpd.RequestHandlerClass = _make_handler(
        {"config_dir": config_dir, "model": model, "view_model": view_model, "convos": convos, "base": base}
    )

    print(
        f"CCDashboard live at {base}  "
        f"({len(view_model['items'])} config items, {len(convos)} conversations)"
    )
    print("Press Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(base)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping CCDashboard server.")
    finally:
        httpd.server_close()
