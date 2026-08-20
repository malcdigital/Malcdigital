"""Local dashboard server.

Built on the standard library's HTTP server rather than a framework. The whole
surface is a handful of read-mostly pages plus two POST actions, so a framework
would add an install step and a dependency to maintain in exchange for very
little. It also means ``quantdesk serve`` works on a fresh Python with nothing
but the desk's own requirements installed.

**This binds to localhost by default and has no authentication.** Anyone who can
reach the port can approve trades. Binding to 0.0.0.0 so a phone on the same
Wi-Fi can reach it exposes it to everyone else on that network too, which is why
it is opt-in via --host rather than the default.
"""

from __future__ import annotations

import json
import threading
import urllib.parse
from datetime import date
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from quantdesk.config import Settings
from quantdesk.web import views


class DeskHandler(BaseHTTPRequestHandler):
    """Routes requests to the view layer. One engine is shared, under a lock."""

    engine = None
    settings: Settings | None = None
    lock = threading.Lock()
    server_version = "quantdesk"
    sys_version = ""

    # --- plumbing -----------------------------------------------------------
    def log_message(self, fmt, *args):  # noqa: A003 - stdlib signature
        return  # the desk prints its own line; stdlib logging is noise here

    def _send(self, body: str, status: int = 200, content_type: str = "text/html") -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        # The page is entirely self-contained, so nothing external may load.
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
            "form-action 'self'",
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def _redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    # --- routes -------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - stdlib signature
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        query = urllib.parse.parse_qs(parsed.query)

        try:
            with self.lock:
                if route == "/":
                    self._send(views.dashboard(self.engine))
                elif route == "/ideas":
                    self._send(views.ideas(self.engine))
                elif route == "/positions":
                    self._send(views.positions(self.engine))
                elif route == "/history":
                    self._send(views.history(self.engine))
                elif route == "/symbol":
                    symbol = (query.get("s") or [""])[0].upper()
                    if not symbol:
                        self._redirect("/")
                        return
                    self._send(views.symbol_detail(self.engine, symbol))
                elif route == "/api/state":
                    self._send(
                        json.dumps(views.state_json(self.engine), indent=2),
                        content_type="application/json",
                    )
                else:
                    self._send(views.not_found(route), status=404)
        except Exception as exc:  # a view error must not kill the server
            self._send(views.error_page(exc), status=500)

    def do_POST(self) -> None:  # noqa: N802 - stdlib signature
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        form = {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}

        try:
            with self.lock:
                if route == "/approve":
                    self._decide(form, approve=True)
                elif route == "/reject":
                    self._decide(form, approve=False)
                elif route == "/run":
                    self.engine.run_daily(
                        max_new_ideas=int(form.get("ideas", 5)), write_files=False
                    )
                    self._redirect("/ideas")
                else:
                    self._send(views.not_found(route), status=404)
        except Exception as exc:
            self._send(views.error_page(exc), status=500)

    def _decide(self, form: dict, approve: bool) -> None:
        try:
            proposal_id = int(form.get("id", ""))
        except ValueError:
            self._redirect("/ideas")
            return
        if approve:
            self.engine.approve_proposal(proposal_id, date.today())
        else:
            self.engine.reject_proposal(proposal_id)
        self._redirect("/ideas")


def serve(
    engine, host: str = "127.0.0.1", port: int = 8000, open_browser: bool = False
) -> None:
    """Run the dashboard until interrupted."""
    DeskHandler.engine = engine
    DeskHandler.settings = engine.settings

    httpd = ThreadingHTTPServer((host, port), DeskHandler)
    shown = "localhost" if host in ("127.0.0.1", "localhost") else host
    print(f"\n  QuantDesk dashboard: http://{shown}:{port}")
    if host not in ("127.0.0.1", "localhost"):
        print("  Reachable from other devices on this network.")
        print("  There is no authentication - anyone who can reach this port")
        print("  can approve trades. Only do this on a network you trust.")
    else:
        print("  Bound to localhost only. Use --host 0.0.0.0 to reach it from")
        print("  your phone on the same Wi-Fi (see the warning in --help).")
    print("  Ctrl-C to stop.\n")

    if open_browser:
        import webbrowser

        webbrowser.open(f"http://{shown}:{port}")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped")
    finally:
        httpd.server_close()
