"""Fallback HTTP server using only the Python standard library.

Same routes as ``api/app.py`` (FastAPI). Use it when FastAPI is not available:

    python -m api.stdlib_server            # http://127.0.0.1:8000

It also serves the built frontend from ``frontend/dist`` if present.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from supersede.service import Supersede

svc = Supersede()
svc.seed_demo()
DIST = Path(os.environ.get("SUPERSEDE_DIST", Path(__file__).resolve().parents[2] / "frontend" / "dist"))

ROUTES: list[tuple[str, re.Pattern, str]] = [
    ("GET", re.compile(r"^/api/health$"), "health"),
    ("GET", re.compile(r"^/api/overview$"), "overview"),
    ("GET", re.compile(r"^/api/runs$"), "runs"),
    ("POST", re.compile(r"^/api/runs$"), "start"),
    ("GET", re.compile(r"^/api/runs/(?P<id>[^/]+)$"), "report"),
    ("GET", re.compile(r"^/api/runs/(?P<id>[^/]+)/steps/(?P<step>\d+)/state$"), "state"),
    ("POST", re.compile(r"^/api/runs/(?P<id>[^/]+)/resume$"), "resume"),
    ("POST", re.compile(r"^/api/runs/(?P<id>[^/]+)/fork$"), "fork"),
    ("POST", re.compile(r"^/api/runs/(?P<id>[^/]+)/rules$"), "rules"),
    ("POST", re.compile(r"^/api/runs/(?P<id>[^/]+)/feedback$"), "feedback"),
    ("POST", re.compile(r"^/api/demo/reset$"), "reset"),
]


def handle(name: str, p: dict, q: dict, body: dict):
    if name == "health":
        return {"ok": True, "llm": svc.llm_mode}
    if name == "overview":
        return svc.overview()
    if name == "runs":
        return svc.list_runs(include_forks=q.get("include_forks", ["false"])[0] == "true")
    if name == "start":
        if not body.get("customer_id") and not body.get("inputs"):
            raise ValueError("give customer_id or inputs")
        return svc.start_run(customer_id=body.get("customer_id"), inputs=body.get("inputs"),
                             run_time=body.get("run_time", "2026-10-15"), options=body.get("options"))
    if name == "report":
        return svc.report(p["id"], refresh=q.get("refresh", ["false"])[0] == "true")
    if name == "state":
        return svc.state(p["id"], int(p["step"]))
    if name == "resume":
        if body.get("action") not in ("approve", "edit", "reject"):
            raise ValueError("action must be approve, edit or reject")
        return svc.resume(p["id"], body["action"], swaps=body.get("swaps"), note=body.get("note", ""))
    if name == "fork":
        return svc.fork(p["id"], from_step=int(body["from_step"]), swaps=body.get("swaps"), guard=body.get("guard"),
                        reason=body.get("reason", "manual fork"))
    if name == "rules":
        return svc.set_rule(p["id"], body["key"], bool(body["on"]))
    if name == "feedback":
        return svc.add_feedback(p["id"], body["verdict"], body.get("note", ""), body.get("author", "reviewer"))
    if name == "reset":
        svc.reset_demo()
        return {"ok": True, "runs": len(svc.store.list_runs())}
    raise KeyError(name)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, payload, ctype: str = "application/json") -> None:
        data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _dispatch(self, method: str) -> None:
        url = urlparse(self.path)
        if not url.path.startswith("/api/"):
            return self._static(url.path)
        for m, pattern, name in ROUTES:
            match = pattern.match(url.path)
            if m == method and match:
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(length) or b"{}") if length else {}
                    return self._send(200, handle(name, match.groupdict(), parse_qs(url.query), body))
                except KeyError as exc:
                    return self._send(404, {"detail": f"not found: {exc}"})
                except (ValueError, TypeError) as exc:
                    return self._send(400, {"detail": str(exc)})
                except Exception as exc:  # pragma: no cover
                    traceback.print_exc()
                    return self._send(500, {"detail": f"{type(exc).__name__}: {exc}"})
        self._send(404, {"detail": "no such route"})

    def _static(self, path: str) -> None:
        if not DIST.is_dir():
            return self._send(404, {"detail": "frontend not built; run npm run build in frontend/"})
        f = (DIST / path.lstrip("/")).resolve()
        if not str(f).startswith(str(DIST.resolve())) or not f.is_file():
            f = DIST / "index.html"
        self._send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream")

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s %s\n" % (self.command, self.path))


def main(port: int = 8000) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Supersede API on http://127.0.0.1:{port}  (model: {svc.llm_mode})")
    server.serve_forever()


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8000)
