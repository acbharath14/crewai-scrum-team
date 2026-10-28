# Implementation notes (Developer agent, canned example)

## STORY-1 — Create a task
- `demo_app/store.py`: `TaskStore.create()` validates via
  `validate_task_data()` (title required, enums enforced, unknown fields
  rejected) and assigns integer ids from 1.
- `demo_app/server.py`: `POST /tasks` returns 201; 422 on validation
  failure, 400 on malformed JSON.

## STORY-2 — List and filter tasks
- `TaskStore.list(status=, assignee=)` filters in memory.
- `GET /tasks?status=&assignee=` passes query params through.

## STORY-3 — Update a task's status
- `TaskStore.update()` validates partial payloads and never wipes
  untouched fields; `PATCH /tasks/<id>` returns 404 for missing ids.

## STORY-4 — Delete a task (NOT in this sprint)
- Estimation diverged (Developer 8, SDET 3, Analyst 5: two Fibonacci
  steps apart), so no locked estimate exists and the story fails the
  Definition of Ready. It stays in the backlog for an estimation
  discussion. The store already implements `delete()`; the sprint
  simply does not claim it.

## Deploy (local only)
"Deploy" in this repo means: start the app server on localhost and run
a smoke check against it. No cloud target exists. The scripted demo
verifies the increment by running the demo_app pytest suite for real.
