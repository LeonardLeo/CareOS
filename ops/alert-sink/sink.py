"""A webhook receiver that prints the alerts Alertmanager sends it.

Exists so the local stack demonstrates the whole path — a metric changing, a rule firing,
Alertmanager routing it, something receiving it — rather than stopping at "Prometheus says the
rule is pending". The step most likely to be broken in an alerting setup is the last one, and
it is the only step you cannot verify by reading configuration.

**Not a production receiver.** It has no persistence, no retry, no deduplication, and no
authentication. Wiring `page` to a real pager needs credentials this repository does not hold;
until that happens, the honest description of this system is that its alerts reach a log line
in a container, which is not the same as being on call.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 9099


class Sink(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's naming
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"unparsed": raw.decode("utf-8", "replace")}

        route = self.path.lstrip("/") or "unrouted"
        for alert in payload.get("alerts", [{}]):
            labels = alert.get("labels", {})
            annotations = alert.get("annotations", {})
            print(
                json.dumps(
                    {
                        "received_at": datetime.now(UTC).isoformat(),
                        "route": route,
                        "status": alert.get("status", payload.get("status", "unknown")),
                        "alert": labels.get("alertname", "?"),
                        "severity": labels.get("severity", "?"),
                        "environment": labels.get("environment", "?"),
                        "summary": annotations.get("summary", ""),
                    }
                ),
                flush=True,  # unbuffered, or `docker compose logs` shows nothing until exit
            )

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def do_GET(self) -> None:  # noqa: N802
        """Liveness, so compose can tell the difference between starting and broken."""
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *_args: object) -> None:
        """Silence the default per-request line; the JSON above is the useful output."""


if __name__ == "__main__":
    print(f"alert sink listening on :{PORT}", file=sys.stderr, flush=True)
    HTTPServer(("0.0.0.0", PORT), Sink).serve_forever()
