# Code Review — TaskBoard

Top 4 issues, ordered by business impact. Line numbers refer to the code at the time of review (commit `110bd45`); issue #1 is fixed in `47ac5a3`.

| # | Issue | Category | Severity | Status |
|---|-------|----------|----------|--------|
| 1 | Task PATCH has no authorization check | Security | **Critical** | ✅ Fixed (Part 2) |
| 2 | Raw SQL with string interpolation in task search | Security | **Critical** | Open |
| 3 | Assignee not validated as a project member | Data Integrity | High | Open |
| 4 | Weak auth/config defaults (30-day JWT, fallback secret, open CORS, DEBUG on) | Security | Medium | Open |

---

## 1. Task PATCH has no authorization check — Critical

- **File:** `backend/projects/views.py` lines 165–185 (`TaskDetailView.patch`)
- **Category:** Security (broken access control / IDOR)
- **Severity:** Critical

**Description.** `PATCH /api/tasks/:id` loads the task and applies changes without checking that the caller is a member of the task's project, let alone an admin/member. Any authenticated user — a viewer, or someone with no relationship to the project — can rename, reassign or move any task whose UUID they know. `DELETE` on the same view does check membership, so the inconsistency is clearly unintended. Task IDs are also exposed to viewers via the list endpoint, so viewers can trivially edit everything they can see.

**Recommended fix.** Apply the same rule used by create/delete: resolve the membership for `task.project_id` and return 403 unless the role is `admin` or `member`. Add regression tests for viewer, non-member and member.

**Proof — before fix** (logged in as `dev@example.com`, a *viewer* on Q3 Launch):

```bash
curl -i -X PATCH localhost:8000/api/tasks/$TASK \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"title":"edited by a viewer"}'
```
```
HTTP/1.1 200 OK
Content-Type: application/json

{"task":{"id":"290353c0-01f1-4eae-93ec-38f79bddd951","project_id":"0e01f768-d0cf-4b63-8130-03f9bad6dd3d","title":"edited by a viewer","description":"Detail for: Finalize launch date with marketing","status":"done", ... }}
```

**Proof — after fix** (`47ac5a3`, same token, same request):

```bash
curl -i -X PATCH localhost:8000/api/tasks/$TASK \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"title":"edited by a viewer again"}'
```
```
HTTP/1.1 403 Forbidden
Content-Type: application/json

{"error":"viewers cannot update tasks"}
```

Tests added in `backend/projects/tests.py::TestTaskUpdatePermissions` (viewer → 403, non-member → 403, member → 200). Backend suite: 18 passed.

---

## 2. Raw SQL with string interpolation in task search — Critical

- **File:** `backend/projects/views.py` lines 111–123 (`TaskListCreateView.get`, `?q=` branch)
- **Category:** Security
- **Severity:** Critical

**Description.** When `?q=` is supplied, the view builds a SQL string with an f-string and passes it straight to `cursor.execute()`. User input is never parameterised, so the query text is attacker-controlled — a classic SQL injection risk that could expose data from other projects or tables. The branch also returns raw DB rows, so search results have a different shape from the normal list (no nested `assignee`), which is a latent frontend bug.

**Recommended fix.** Drop the raw SQL and use the ORM:
`Task.objects.filter(project_id=project_id).filter(Q(title__icontains=q) | Q(description__icontains=q)).select_related('assignee').order_by('position')`, then serialise with `TaskSerializer`. If raw SQL is ever needed, use `cursor.execute(sql, params)` with placeholders.

---

## 3. Assignee is not validated as a project member — High

- **File:** `backend/projects/views.py` line 156 (create) and lines 188–189 (update)
- **Category:** Data Integrity
- **Severity:** High

**Description.** `assigneeId` is written directly to the task without checking that the user exists or belongs to the project. Tasks can be assigned to arbitrary users from other projects, and because the task serializer embeds the assignee, that user's name and email are then exposed to everyone in the project. A malformed or unknown ID surfaces as an unhandled 500 (FK/UUID error) instead of a 400.

**Recommended fix.** Before saving, verify `Membership.objects.filter(project_id=task.project_id, user_id=assignee_id).exists()`; return 400 `invalid assignee` otherwise. Validate the UUID format in a serializer rather than relying on the database to reject it.

---

## 4. Weak authentication and configuration defaults — Medium

- **File:** `backend/taskboard/settings.py` lines 7–8, 52, 56
- **Category:** Security
- **Severity:** Medium

**Description.** Access tokens live for 30 days with no refresh/rotation or revocation, so a leaked token (stored in `localStorage` on the frontend) stays valid for a month. `SECRET_KEY` silently falls back to a short hard-coded value (pytest already emits `InsecureKeyLengthWarning`), `DEBUG` defaults to `true`, and `CORS_ALLOW_ALL_ORIGINS = True` lets any site call the API. Individually these are config issues; together they make a production deployment unsafe by default.

**Recommended fix.** Short-lived access tokens (5–15 min) plus refresh tokens with rotation/blacklist; fail fast if `DJANGO_SECRET_KEY` is unset outside dev; default `DEBUG` to false; restrict CORS to the frontend origin.

---

## Other findings (not in top 4)

- **Performance** — `ProjectListCreateView.get` (line 39) prefetches *every task of every project* just to call `.count()`. Use `.annotate(task_count=Count('project__tasks'))` instead.
- **Data integrity** — task position is computed as `max + 1` (line 148) without a lock or unique constraint, so concurrent creates can produce duplicate positions.
- **Testing** — no tests covered task PATCH authorization (now added) or the search endpoint.
- **Architecture / Data integrity** — the API returns snake_case keys (`assignee_id`, `owner_id`, `created_at`) while the frontend types (`frontend/src/types/index.ts`) expect camelCase (`assigneeId`, `ownerId`). Fields read through the camelCase names are `undefined` at runtime, e.g. the task dialog unassigned the task on every save (fixed in `e033afd`). Fix: a camelCase renderer/parser for DRF (e.g. `djangorestframework-camel-case`) or schema validation at the client boundary.
- **Data integrity** — `Task.Meta.indexes` declares an unnamed index while `0001_initial.py` names it `tasks_project_status_idx`, so `makemigrations` always reports a pending rename. Fix: add `name='tasks_project_status_idx'` to the model.
- **Data integrity** — the first version of comments used `on_delete=CASCADE`, which would let deleting a task, project or user silently erase the audit trail. Fixed in `07a2b19` (PROTECT, 409 responses, DB trigger); see DESIGN_NOTES.md.
