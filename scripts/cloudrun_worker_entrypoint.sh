#!/bin/sh
# Cloud Run requires a listening HTTP port. ARQ does not expose one, so we serve /health
# and /ready on $PORT in the background and run the worker in the foreground.
set -e

PORT="${PORT:-8080}"

python - <<'PY' &
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

from meeting_assistant.core.config import Settings
from meeting_assistant.services.worker_readiness import check_arq_worker_health


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path in ("/", "/health"):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
            return
        if self.path == "/ready":
            settings = Settings()
            worker_status, worker_detail = check_arq_worker_health(settings)
            checks = {"worker": worker_status}
            details = {"worker": worker_detail} if worker_detail else {}
            is_ready = worker_status in {"ok", "skipped"}
            body = json.dumps(
                {
                    "status": "ready" if is_ready else "degraded",
                    "checks": checks,
                    **({"details": details} if details else {}),
                }
            ).encode()
            self.send_response(200 if is_ready else 503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, *_args: object) -> None:
        return


HTTPServer(("", int(os.environ["PORT"])), HealthHandler).serve_forever()
PY

exec arq meeting_assistant.worker.WorkerSettings
