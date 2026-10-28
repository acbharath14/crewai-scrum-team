"""Stdlib-only HTTP API for the Task Board (demo_app).

Routes:
  GET    /tasks            list tasks (?status=, ?assignee= filters)
  POST   /tasks            create a task (201)
  GET    /tasks/<id>       fetch one task
  PATCH  /tasks/<id>       partial update
  DELETE /tasks/<id>       delete (204)

Errors: 400 for bad JSON, 422 for validation failures, 404 for
missing tasks or unknown routes. Run with:

    python -m demo_app.server [port]      # default port 8000
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from .store import TaskStore, ValidationError, NotFoundError

STORE = TaskStore()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # keep stdout clean for demos
        pass

    # -- helpers ---------------------------------------------------------
    def _send_json(self, status, payload=None):
        body = b"" if payload is None else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw or b"{}")
        except json.JSONDecodeError:
            raise ValidationError("request body must be valid JSON")

    def _task_id(self, parts):
        if len(parts) != 2 or not parts[1].isdigit():
            return None
        return int(parts[1])

    # -- verbs -----------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        parts = [p for p in parsed.path.split("/") if p]
        try:
            if parts == ["tasks"]:
                query = parse_qs(parsed.query)
                tasks = STORE.list(
                    status=query.get("status", [None])[0],
                    assignee=query.get("assignee", [None])[0],
                )
                self._send_json(200, tasks)
            elif len(parts) == 2 and parts[0] == "tasks":
                task_id = self._task_id(parts)
                if task_id is None:
                    self._send_json(404, {"error": "not found"})
                else:
                    self._send_json(200, STORE.get(task_id))
            else:
                self._send_json(404, {"error": "not found"})
        except NotFoundError as exc:
            self._send_json(404, {"error": str(exc)})

    def do_POST(self):
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        if parts != ["tasks"]:
            self._send_json(404, {"error": "not found"})
            return
        try:
            self._send_json(201, STORE.create(self._read_json()))
        except ValidationError as exc:
            code = 400 if "valid JSON" in str(exc) else 422
            self._send_json(code, {"error": str(exc)})

    def do_PATCH(self):
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        task_id = self._task_id(parts) if parts and parts[0] == "tasks" else None
        if task_id is None:
            self._send_json(404, {"error": "not found"})
            return
        try:
            self._send_json(200, STORE.update(task_id, self._read_json()))
        except NotFoundError as exc:
            self._send_json(404, {"error": str(exc)})
        except ValidationError as exc:
            code = 400 if "valid JSON" in str(exc) else 422
            self._send_json(code, {"error": str(exc)})

    def do_DELETE(self):
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        task_id = self._task_id(parts) if parts and parts[0] == "tasks" else None
        if task_id is None:
            self._send_json(404, {"error": "not found"})
            return
        try:
            STORE.delete(task_id)
            self._send_json(204)
        except NotFoundError as exc:
            self._send_json(404, {"error": str(exc)})


def main(argv=None):
    port = int((argv or sys.argv)[1]) if len(sys.argv) > 1 else 8000
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Team Task Board API on http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
