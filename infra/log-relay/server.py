"""Minimal Docker log relay — stdlib only, no pip dependencies.

Reads container logs from the Docker Engine API via the Unix domain socket
and serves them over HTTP. This isolates Docker socket access into a single
container with no secrets, database credentials, or external network access.
"""

from __future__ import annotations

import http.client
import json
import socket
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

ALLOWED_CONTAINERS: set[str] = {
    "sports-api",
    "sports-api-worker",
    "sports-api-training-worker",
    "sports-scraper",
    "sports-social-scraper",
}

DOCKER_SOCKET = "/var/run/docker.sock"
PORT = 9999


class _DockerSocketConnection(http.client.HTTPConnection):
    """HTTPConnection subclass that talks to the Docker Unix domain socket."""

    def __init__(self) -> None:
        super().__init__("localhost")

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(DOCKER_SOCKET)


def _strip_docker_frame_headers(raw: bytes) -> str:
    """Strip 8-byte Docker stream multiplexing frame headers.

    The Docker Engine API returns log output with an 8-byte header per frame:
      - byte 0: stream type (0=stdin, 1=stdout, 2=stderr)
      - bytes 1-3: padding
      - bytes 4-7: payload size (big-endian uint32)
    """
    result: list[str] = []
    offset = 0
    while offset + 8 <= len(raw):
        size = int.from_bytes(raw[offset + 4 : offset + 8], "big")
        if offset + 8 + size > len(raw):
            break
        payload = raw[offset + 8 : offset + 8 + size]
        result.append(payload.decode("utf-8", errors="replace"))
        offset += 8 + size

    if not result and raw:
        return raw.decode("utf-8", errors="replace")

    return "".join(result)


def _fetch_logs(container: str, lines: int) -> tuple[int, dict[str, object]]:
    """Fetch logs from Docker Engine API. Returns (http_status, response_body)."""
    conn = _DockerSocketConnection()
    try:
        path = (
            f"/containers/{container}/logs"
            f"?stdout=1&stderr=1&tail={lines}&timestamps=1"
        )
        conn.request("GET", path)
        resp = conn.getresponse()

        if resp.status == 404:
            return 404, {"error": f"Container '{container}' not found. Is it running?"}

        if resp.status != 200:
            return 502, {"error": f"Docker API returned status {resp.status}"}

        raw = resp.read()
        log_text = _strip_docker_frame_headers(raw)

        return 200, {"container": container, "lines": lines, "logs": log_text}
    finally:
        conn.close()


class LogRelayHandler(BaseHTTPRequestHandler):
    """Handle GET /logs?container=X&lines=N requests."""

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)

        if parsed.path != "/logs":
            self._respond(404, {"error": "Not found"})
            return

        params = parse_qs(parsed.query)
        container = params.get("container", [None])[0]  # type: ignore[list-item]
        if not container:
            self._respond(400, {"error": "Missing 'container' query parameter"})
            return

        if container not in ALLOWED_CONTAINERS:
            self._respond(
                400,
                {
                    "error": f"Container '{container}' not in allow list. "
                    f"Allowed: {', '.join(sorted(ALLOWED_CONTAINERS))}"
                },
            )
            return

        lines_raw = params.get("lines", ["1000"])[0]
        try:
            lines = max(1, min(int(lines_raw), 10000))
        except ValueError:
            self._respond(400, {"error": f"Invalid 'lines' value: {lines_raw}"})
            return

        try:
            status, body = _fetch_logs(container, lines)
        except OSError as exc:
            self._respond(
                503,
                {"error": f"Docker socket unavailable: {exc}"},
            )
            return

        self._respond(status, body)

    def _respond(self, status: int, body: dict[str, object]) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args: object) -> None:
        """Write access logs to stderr."""
        print(f"[log-relay] {fmt % args}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), LogRelayHandler)
    print(f"[log-relay] Listening on :{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()
