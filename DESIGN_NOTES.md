# Design Notes

Decisions and trade-offs behind Parts 2, 3a, 3b and 3c. Commit references are on `master`.

## Part 3c — Airtable export (`4e7b3d7`)

**Library: `pyairtable`, not the `airtable` npm package.** The assignment doc says to use the npm
package and names `src/lib/airtable-mock.ts`, but the repo's README says *"The backend uses
`pyairtable` for real API calls. `backend/projects/airtable_mock.py` is a test double"*, and
`pyairtable` is already pinned in `requirements.txt`. The export has to run server-side, and the
server is Django, so I followed the repo. Using the npm package would mean adding a Node service
just to make HTTP calls. The test double is `backend/projects/airtable_mock.py`.

**Safe to re-run.** Each task becomes one Airtable row keyed on `Task ID` (the task UUID), written
with `batch_upsert(..., key_fields=["Task ID"])`. Running the export twice updates the same rows
instead of duplicating them. This was verified against the real base: 7 rows after the first run
and still 7 after the second (`docs/airtable-export.png`).

**Error handling** (`backend/projects/airtable_export.py`):

| Failure | Behaviour |
|---|---|
| 429, 408, 5xx, timeout, connection error | Retried up to 4 attempts with exponential backoff and jitter; `Retry-After` is honoured |
| 422 or other 4xx on a batch | Not retried as-is. The batch is re-sent one record at a time, so only the bad record fails |
| 401 / 403 / 404 (bad token, no access, wrong base or table) | Aborts the whole export with HTTP 502, because every later request would fail the same way |
| Missing credentials | HTTP 503 with a clear message, before any call is made |

`pyairtable`'s built-in urllib3 retry is turned off (`retry_strategy=False`), so the retry policy
lives in one place and is covered by tests. Requests go out in batches of 10 (Airtable's maximum),
about 0.2s apart, to stay under the limit of 5 requests per second per base. The response is
`{total, exported, failed: [{taskId, title, error}]}`. A partial failure still returns 200,
because the export as a whole succeeded and the failures are reported per record.

**Synchronous.** 1,000 tasks is about 100 requests, roughly 25 seconds, which is acceptable for an
explicit button press. The async version would enqueue a job, return `202` with a job id, and have
the UI poll for status. It wasn't built.

**Known limitation.** The export is one-way and upsert-only. A task deleted in TaskBoard stays in
Airtable. Mirroring deletes would need a reconcile pass (list Airtable rows for the project, delete
the ones whose Task ID no longer exists), and that's risky to do automatically.

## Part 3a — Task comments (`ec48817`, `07a2b19`)

The doc notes that comments are *"part of the engagement audit trail"*, so "append-only" has to hold
against every way a row can change or disappear, not only the comment endpoints:

1. **API:** only list and create exist. PUT, PATCH and DELETE return 405.
2. **ORM:** `Comment.save()` and `Comment.delete()` refuse to touch an existing row. `task` and
   `author` are `on_delete=PROTECT`, so deleting a task, project or user that has comments raises
   instead of silently cascading the comments away (the first version used CASCADE; `07a2b19`
   fixed this).
3. **API, indirect paths:** `DELETE /api/tasks/:id` and `DELETE /api/projects/:id` return 409 when
   comments exist, instead of a 500 from the `ProtectedError`.
4. **Database:** a Postgres trigger (migration `0003`) rejects row-level UPDATE and DELETE on
   `comments`. This also covers bulk queryset operations and raw SQL.

Trade-off: a task with comments can't be deleted. Moving it to `done` is the supported way to close
it. A soft-delete or archive flag would be the next step if teams need to hide old tasks.

`seed` wipes every table, so it now refuses to run once comments exist. I didn't change the seed
command or its data. Instead, `python manage.py reset_audit_trail --yes` is a separate, deliberate
dev-only step that TRUNCATEs comments (the trigger blocks row DELETE, not TRUNCATE).

Authorization: any project member, including viewers, can read. Admins and members can post.
Viewers get 403. Non-members get 404, so task ids don't leak. The body is trimmed, can't be empty,
and is capped at 5,000 characters.

## Part 3b — Activity feed (`e033afd`)

Events: `task_created`, `status_changed` (from/to), `assignee_changed` (from/to) and
`comment_added`, each with the actor and a timestamp. `GET /api/projects/:id/activity?limit=50`
returns newest first for one project. Any member can read it, viewers included. Non-members get
403.

**If the activity write fails, the change rolls back.** The change and its activity row are written
inside one `transaction.atomic()` block. The feed is an audit trail, and a change with no record of
who made it is worse than a failed request the user can simply retry. Both writes go to the same
Postgres database, so atomicity costs almost nothing, with no distributed transaction or outbox
needed. The opposite choice, best-effort logging, would fit an external sink such as an analytics
pipeline or Airtable, which is why the export stays outside any transaction. Tests force the
activity write to fail and check that the task create, the status change and the comment are all
rolled back (`test_activity.py::TestActivityIsAtomicWithTheChange`).

`Activity.task` is `SET_NULL`, with a snapshot of `task_title`, so a task's history survives the task
being deleted. `Activity.project` is `CASCADE`: deleting a whole project is an admin action that
removes its feed too. Projects that have comments can't be deleted anyway (see 3a).

## Fixes made along the way

- **Part 2 (`47ac5a3`):** `PATCH /api/tasks/:id` had no membership or role check. Any logged-in
  user, including a viewer or a non-member, could edit any task. It now uses the same rule as
  create and delete.
- **Task dialog dropped the assignee on save (`e033afd`):** the API serialises `assignee_id`, but
  the UI read `assigneeId` (undefined), so saving a task from the dialog unassigned it. With the
  activity feed this also logged false "unassigned" events. The fix is to fall back to the nested
  `assignee.id`. The broader snake_case-vs-camelCase mismatch between the API and the frontend
  types is noted in REVIEW.md. The new endpoints (export, comments, activity) return camelCase
  keys that match the frontend types.
- **Docker env (`110bd45`):** `settings.py` doesn't load `.env`, so `env_file: .env` was added to the
  backend service to pass the Airtable credentials in.

## Incident during the session

While testing the comment protection, `reset_audit_trail --yes` was run by mistake before the new
migration and tests. That erased the demo comment and let the seeded task *"Finalize launch date
with marketing"* be deleted. The task was recreated with its original UUID and the exact seed
values (title, description, `done`, Meera, position 0), so the database and the Airtable rows match
the seed again, and the demo was re-run properly (409 on delete, comment preserved). The seed
command and seed data were not changed.
