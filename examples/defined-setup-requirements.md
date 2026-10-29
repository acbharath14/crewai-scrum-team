# Defined-setup requirements: Team Task Board

Copy this file, edit it for your product, then run the crew with
`--requirement <your file> --target demo_app`. The crew builds ONLY
what is written here. Anything not written here is out of scope,
not an invitation to invent features.

## Product

Team Task Board API: tasks with title, status, assignee, and
priority, with CRUD operations and validation. Standard library
only, no new dependencies.

## Scope

- Create a task with a non-empty title, status, assignee, and
  priority.
- List tasks, with filtering by status and by assignee.
- Update a task's title, status, assignee, or priority.
- Reject a task with an empty title, and reject an unknown status
  value, with a clear error.
- Keep existing behaviour and existing tests passing.

## Out of scope

- User accounts, authentication, and login.
- Persistence to disk or a database; in-memory storage is accepted.
- A web UI; API only.
- Cloud deployment.

## Acceptance criteria

- AC-1: Creating a valid task returns the task with its fields set.
- AC-2: Listing with a status filter returns only tasks with that
  status; listing with an assignee filter returns only that
  assignee's tasks.
- AC-3: Updating a task changes only the fields supplied, and
  preserves the rest.
- AC-4: Creating a task with an empty title is rejected with an
  error, and no task is created.
- AC-5: Creating or updating a task with an unknown status is
  rejected with an error.

## Target

- App code: `demo_app/`
- Tests: `tests/`, one file per story, importing from `demo_app`.
