#!/usr/bin/env python3
"""Local HTTP server that simulates Discord and Telegram webhooks.

Used to prove the reminder path end to end without touching a real account:
the CLI is pointed at http://127.0.0.1:PORT/... and this server records the
exact payload it would have delivered.

    ./tests/mock_server.py 8765 &
    SINAR_DISCORD_WEBHOOK=http://127.0.0.1:8765/discord ./sc-api notify-test
    cat /tmp/scapi-mock.jsonl
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

LOG = "/tmp/scapi-mock.jsonl"


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 (stdlib naming)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode(errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"_raw": raw}
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"path": self.path, "payload": payload}) + "\n")
        body = json.dumps({"ok": True, "id": "mock"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # quiet
        pass


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    open(LOG, "w").close()
    print(f"mock webhook on http://127.0.0.1:{port}  (log: {LOG})", flush=True)
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()