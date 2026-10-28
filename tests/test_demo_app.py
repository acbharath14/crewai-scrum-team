"""Tests for the demo_app Task Board (store + HTTP API).

These are the tests the scripted demo runs FOR REAL and maps onto the
SDET traceability matrix (see examples/sample-run/tests_map.json).
"""

import json
import threading
import urllib.request
import urllib.error
import pytest

from demo_app.store import TaskStore, ValidationError, NotFoundError
from demo_app.server import Handler, STORE
from http.server import ThreadingHTTPServer


# -- store: create ----------------------------------------------------------

def test_create_task_valid():
    store = TaskStore()
    task = store.create({"title": "Write spec"})
    assert task["id"] == 1
    assert task["status"] == "todo"
    assert task["priority"] == "medium"


def test_create_task_defaults():
    store = TaskStore()
    task = store.create({"title": "Write spec", "assignee": "Ada"})
    assert task["status"] == "todo"
    assert task["assignee"] == "Ada"


def test_create_task_missing_title():
    store = TaskStore()
    with pytest.raises(ValidationError):
        store.create({"priority": "high"})


def test_create_task_invalid_priority():
    store = TaskStore()
    with pytest.raises(ValidationError):
        store.create({"title": "X", "priority": "urgent"})


# -- store: list / filter -----------------------------------------------------

def test_list_tasks():
    store = TaskStore()
    store.create({"title": "A"})
    store.create({"title": "B"})
    assert len(store.list()) == 2


def test_list_tasks_filter_status():
    store = TaskStore()
    store.create({"title": "A"})
    store.create({"title": "B", "status": "done"})
    assert len(store.list(status="done")) == 1
    assert store.list(status="done")[0]["title"] == "B"


def test_list_tasks_filter_assignee():
    store = TaskStore()
    store.create({"title": "A", "assignee": "Ada"})
    store.create({"title": "B", "assignee": "Grace"})
    assert len(store.list(assignee="Ada")) == 1


# -- store: update / delete -----------------------------------------------------

def test_update_task_status():
    store = TaskStore()
    task = store.create({"title": "A"})
    updated = store.update(task["id"], {"status": "in_progress"})
    assert updated["status"] == "in_progress"


def test_update_task_invalid_status():
    store = TaskStore()
    task = store.create({"title": "A"})
    with pytest.raises(ValidationError):
        store.update(task["id"], {"status": "shipped"})


def test_update_task_not_found():
    store = TaskStore()
    with pytest.raises(NotFoundError):
        store.update(999, {"status": "done"})


def test_delete_task():
    store = TaskStore()
    task = store.create({"title": "A"})
    assert store.delete(task["id"]) is True
    assert store.list() == []


def test_delete_task_not_found():
    store = TaskStore()
    with pytest.raises(NotFoundError):
        store.delete(999)


# -- HTTP API (real server on an ephemeral localhost port) ----------------------

@pytest.fixture()
def api():
    STORE._tasks.clear()
    STORE._next_id = 1
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield base
    server.shutdown()
    server.server_close()


def _request(base, method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read()
            return resp.status, json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        body = exc.read()
        return exc.code, json.loads(body) if body else None


def test_api_create_task(api):
    status, body = _request(api, "POST", "/tasks", {"title": "Ship it"})
    assert status == 201
    assert body["title"] == "Ship it"
    assert body["id"] == 1


def test_api_list_tasks(api):
    _request(api, "POST", "/tasks", {"title": "A"})
    _request(api, "POST", "/tasks", {"title": "B"})
    status, body = _request(api, "GET", "/tasks")
    assert status == 200
    assert len(body) == 2


def test_api_get_missing_task(api):
    status, body = _request(api, "GET", "/tasks/999")
    assert status == 404
