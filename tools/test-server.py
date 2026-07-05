#!/usr/bin/env python3
"""Throwaway test server for manually exercising scripts/optimize.py.

Serves tools/test-ui.html at / and exposes POST /optimize, which takes a JSON
body {spend: {...}, user: {...}}, writes it to a temp profile YAML, runs
`python3 scripts/optimize.py --profile <tmp> --json`, and returns the
optimizer's JSON verbatim (or {error: ...} with the CLI's stderr on failure).

Not production code — no auth, single-threaded, for local testing only.

Usage:  python3 tools/test-server.py [port]   (default 8321)
"""

import json
import subprocess
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
OPTIMIZER = ROOT / "scripts" / "optimize.py"
UI_HTML = Path(__file__).resolve().parent / "test-ui.html"


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, UI_HTML.read_bytes(), "text/html; charset=utf-8")
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/optimize":
            self._send(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError):
            self._send(400, {"error": "invalid JSON body"})
            return

        profile = {"spend": req.get("spend") or {}, "user": req.get("user") or {}}
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            yaml.safe_dump(profile, f)
            tmp = f.name

        proc = subprocess.run(
            [sys.executable, str(OPTIMIZER), "--profile", tmp, "--json"],
            capture_output=True, text=True, cwd=ROOT, timeout=300)
        Path(tmp).unlink(missing_ok=True)

        if proc.returncode != 0:
            self._send(422, {"error": proc.stderr.strip() or proc.stdout.strip()
                             or f"optimizer exited {proc.returncode}"})
            return
        self._send(200, proc.stdout.encode())

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8321
    print(f"Test UI on http://localhost:{port}  (Ctrl-C to stop)")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
