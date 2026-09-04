"""Lightweight HTTP redirect server for click tracking.

Runs in a background thread alongside bot.py.
Handles GET /go/{deal_id} -> 302 redirect to destination URL + records click.
"""

import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from k4promo.storage import click_store as click_tracker

log = logging.getLogger("k4binho")

_links: dict[str, dict] = {}
_server: HTTPServer | None = None


class _RedirectHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not self.path.startswith("/go/"):
            self.send_error(404)
            return

        deal_id = self.path[4:].split("?")[0].strip("/")
        destination = click_tracker.resolve_link(_links, deal_id)
        if not destination:
            self.send_error(404)
            return

        source = _links.get(deal_id, {}).get("source", "")
        click_tracker.record_click(deal_id, source=source)

        self.send_response(302)
        self.send_header("Location", destination)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def log_message(self, format, *args):
        log.debug("[ClickServer] %s", format % args)


def start(port: int, links: dict[str, dict]) -> None:
    global _links, _server
    _links = links
    _server = HTTPServer(("0.0.0.0", port), _RedirectHandler)
    thread = threading.Thread(target=_server.serve_forever, daemon=True)
    thread.start()
    log.info("[ClickServer] rodando em http://localhost:%d/go/", port)


def stop() -> None:
    global _server
    if _server:
        _server.shutdown()
        _server = None


def tracking_url(base_url: str, deal_id: str) -> str:
    base = base_url.rstrip("/")
    return f"{base}/go/{deal_id}"
