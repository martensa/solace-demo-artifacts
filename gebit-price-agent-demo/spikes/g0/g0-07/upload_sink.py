"""G0-07 HTTP upload sink: stand-in for the BFF in the ingress body-size test.

POST any path -> 200 {"bytes": n, "sha256": "..."}; GET /healthz -> 200.
Stdlib only, keeps nothing (the body is hashed and dropped).
"""
from __future__ import annotations

import hashlib
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    server_version = "gpos-g0-upload/0.1"

    def _reply(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        self._reply(200, {"status": "ok"})

    def do_POST(self) -> None:  # noqa: N802
        left = int(self.headers.get("Content-Length") or 0)
        digest, got = hashlib.sha256(), 0
        while left > 0:
            chunk = self.rfile.read(min(65536, left))
            if not chunk:
                break
            digest.update(chunk)
            got += len(chunk)
            left -= len(chunk)
        self._reply(200, {"bytes": got, "sha256": digest.hexdigest(),
                          "path": self.path})


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
