"""In-memory Task Board store (stdlib only).

One resource: tasks with title / status / assignee / priority.

Validation rules (these are the rules the SDET acceptance tests pin down):
  * title is required and must be a non-empty string.
  * status must be one of todo, in_progress, done (default: todo).
  * priority must be one of low, medium, high (default: medium).
  * assignee is optional; when present it must be a string.
  * unknown fields are rejected, so typos fail loudly instead of
    being silently stored.
"""

from __future__ import annotations

STATUSES = ("todo", "in_progress", "done")
PRIORITIES = ("low", "medium", "high")
_ALLOWED_FIELDS = ("title", "status", "assignee", "priority")


class ValidationError(ValueError):
    """Raised when task data breaks a validation rule."""


class NotFoundError(KeyError):
    """Raised when a task id does not exist."""


def validate_task_data(data, partial=False):
    """Validate a create (partial=False) or update (partial=True) payload."""
    if not isinstance(data, dict):
        raise ValidationError("task data must be a JSON object")
    unknown = sorted(set(data) - set(_ALLOWED_FIELDS))
    if unknown:
        raise ValidationError(f"unknown field(s): {', '.join(unknown)}")
    if not partial or "title" in data:
        title = data.get("title")
        if not isinstance(title, str) or not title.strip():
            raise ValidationError("title is required and must be non-empty")
    if "status" in data and data["status"] not in STATUSES:
        raise ValidationError(f"status must be one of {list(STATUSES)}")
    if "priority" in data and data["priority"] not in PRIORITIES:
        raise ValidationError(f"priority must be one of {list(PRIORITIES)}")
    if "assignee" in data and data["assignee"] is not None \
            and not isinstance(data["assignee"], str):
        raise ValidationError("assignee must be a string")
    return True


class TaskStore:
    """Tiny in-memory store with integer ids starting at 1."""

    def __init__(self):
        self._tasks = {}
        self._next_id = 1

    def create(self, data):
        validate_task_data(data)
        task = {
            "id": self._next_id,
            "title": data["title"].strip(),
            "status": data.get("status", "todo"),
            "assignee": data.get("assignee"),
            "priority": data.get("priority", "medium"),
        }
        self._tasks[self._next_id] = task
        self._next_id += 1
        return dict(task)

    def list(self, status=None, assignee=None):
        tasks = list(self._tasks.values())
        if status is not None:
            tasks = [t for t in tasks if t["status"] == status]
        if assignee is not None:
            tasks = [t for t in tasks if t["assignee"] == assignee]
        return [dict(t) for t in tasks]

    def get(self, task_id):
        try:
            return dict(self._tasks[task_id])
        except KeyError:
            raise NotFoundError(f"task {task_id} not found")

    def update(self, task_id, data):
        validate_task_data(data, partial=True)
        task = self.get(task_id)
        for key, value in data.items():
            task[key] = value.strip() if key == "title" else value
        self._tasks[task_id] = task
        return dict(task)

    def delete(self, task_id):
        self.get(task_id)  # raises NotFoundError when missing
        del self._tasks[task_id]
        return True
