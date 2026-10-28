# EPIC-1: Team Task Board API

## Business goal
As a team lead, I want a shared task board API so the whole team tracks
work in one place instead of in scattered chat messages and spreadsheets.

## Why now
The team has grown past the point where informal tracking works: tasks
get dropped, nobody knows who owns what, and status updates cost a
meeting every time. A single small API with clear rules removes that
coordination tax.

## Scope
One resource — tasks with title, status, assignee, and priority — with
create, list/filter, update, and delete operations, plus validation
rules that reject bad data loudly instead of storing it.

## Out of scope (backlog, not this epic)
- User accounts and authentication.
- Notifications (email, chat) on assignment or status change.
- A web frontend; API consumers are the client for now.
- Persistent database storage; in-memory storage is acceptable for
  this increment and is recorded as known tech debt below.

## Known tech debt accepted by the Product Owner
In-memory storage loses tasks on restart. Accepted for this increment
because the goal is proving the workflow end to end; persistence is
the first backlog item for the next epic.
