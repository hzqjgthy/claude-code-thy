from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from queue import Queue, Empty
from threading import Thread
from urllib.parse import parse_qs, urlparse


@dataclass(slots=True)
class OAuthCallbackResult:
    code: str | None = None
    state: str | None = None
    error: str | None = None


class OAuthCallbackServer:
    def __init__(self, port: int, expected_state: str) -> None:
        self._queue: Queue[OAuthCallbackResult] = Queue(maxsize=1)
        self._expected_state = expected_state
        self._server = HTTPServer(("127.0.0.1", port), self._handler_type())
        self._thread = Thread(target=self._server.serve_forever, name=f"mcp-oauth-{port}", daemon=True)
        self._thread.start()

    @property
    def redirect_uri(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}/callback"

    def wait_for_result(self, timeout_seconds: float = 600.0) -> OAuthCallbackResult:
        try:
            return self._queue.get(timeout=timeout_seconds)
        except Empty:
            return OAuthCallbackResult(error="OAuth callback timed out")

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._thread.is_alive():
            self._thread.join(timeout=1)

    def _handler_type(self):
        queue = self._queue
        expected_state = self._expected_state

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path != "/callback":
                    self.send_response(404)
                    self.end_headers()
                    return
                query = parse_qs(parsed.query)
                result = OAuthCallbackResult(
                    code=_first(query.get("code")),
                    state=_first(query.get("state")),
                    error=_first(query.get("error")),
                )
                if result.state and result.state != expected_state:
                    result = OAuthCallbackResult(error="OAuth state mismatch")
                    body = "OAuth state mismatch. You can close this window."
                    self._respond(400, body)
                elif result.error:
                    self._respond(400, f"OAuth failed: {result.error}. You can close this window.")
                elif result.code:
                    self._respond(200, "OAuth completed. You can close this window.")
                else:
                    result = OAuthCallbackResult(error="Missing authorization code")
                    self._respond(400, "OAuth callback did not include a code. You can close this window.")
                try:
                    queue.put_nowait(result)
                except Exception:
                    pass

            def _respond(self, status: int, body: str) -> None:
                payload = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                _ = (format, args)

        return CallbackHandler


def _first(values: list[str] | None) -> str | None:
    if not values:
        return None
    return values[0]
