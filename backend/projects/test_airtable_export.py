"""Tests for the Airtable export (Part 3c). Uses the in-memory double, never the real API."""
import pytest
from rest_framework.test import APIClient

from users.models import User
from projects import airtable_export
from projects.airtable_export import AirtableFatalError, export_tasks
from projects.airtable_mock import InMemoryAirtableTable
from projects.models import Membership, Project, Task

REAL_GET_TABLE = airtable_export.get_table


@pytest.fixture
def table():
    return InMemoryAirtableTable()


@pytest.fixture
def sleeps(monkeypatch):
    """Record backoff sleeps instead of actually sleeping."""
    calls = []
    monkeypatch.setattr(airtable_export, "_sleep", calls.append)
    return calls


@pytest.fixture
def project(db):
    owner = User.objects.create_user(email="owner@example.com", name="Owner", password="password123")
    project = Project.objects.create(name="Q3 Launch", owner=owner)
    Membership.objects.create(user=owner, project=project, role="admin")
    return project


def make_tasks(project, n):
    return [
        Task.objects.create(project=project, title=f"Task {i}", created_by=project.owner, position=i)
        for i in range(n)
    ]


def tasks_qs(project):
    return Task.objects.filter(project=project).select_related("assignee", "project").order_by("position")


def login_as(role, project):
    user = User.objects.create_user(email=f"{role}@example.com", name=role.title(), password="password123")
    if role != "outsider":
        Membership.objects.create(user=user, project=project, role=role)
    client = APIClient()
    resp = client.post("/api/auth/login", {"email": user.email, "password": "password123"}, format="json")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['token']}")
    return client


# --------------------------------------------------------------------------- #
# Exporter unit tests
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestExportTasks:
    def test_maps_fields_and_batches_by_ten(self, project, table, sleeps):
        make_tasks(project, 23)
        result = export_tasks(tasks_qs(project), table)

        assert result.as_dict() == {"total": 23, "exported": 23, "failed": []}
        assert [len(c) for c in table.calls] == [10, 10, 3]
        row = table.all()[0]["fields"]
        assert set(row) == {"Task ID", "Title", "Description", "Status", "Assignee", "Position", "Project"}
        assert row["Project"] == "Q3 Launch" and isinstance(row["Position"], int)

    def test_rerun_is_idempotent(self, project, table, sleeps):
        tasks = make_tasks(project, 12)
        export_tasks(tasks_qs(project), table)
        tasks[0].title = "Renamed"
        tasks[0].save()
        export_tasks(tasks_qs(project), table)

        assert len(table.rows) == 12  # no duplicates
        assert table.rows[str(tasks[0].id)]["fields"]["Title"] == "Renamed"

    @pytest.mark.parametrize("status", [429, 500, 503, None])  # None = connection error
    def test_transient_errors_are_retried(self, project, table, sleeps, status):
        make_tasks(project, 3)
        table.fail_next(status, times=2)
        result = export_tasks(tasks_qs(project), table)

        assert result.exported == 3 and result.failed == []
        assert len(table.calls) == 3          # 2 failures + 1 success
        assert len(sleeps) == 2               # backed off twice
        assert sleeps[1] > sleeps[0]          # exponential

    def test_retry_after_header_is_honoured(self, project, table, sleeps):
        make_tasks(project, 1)
        table.fail_next(429, retry_after=7)
        export_tasks(tasks_qs(project), table)
        assert sleeps == [7.0]

    def test_gives_up_after_max_attempts(self, project, table, sleeps):
        make_tasks(project, 3)
        table.fail_next(503, times=10)
        result = export_tasks(tasks_qs(project), table)

        assert result.exported == 0 and len(result.failed) == 3
        assert len(table.calls) == airtable_export.MAX_ATTEMPTS
        assert "503" in result.failed[0]["error"]

    def test_permanent_error_is_not_retried(self, project, table, sleeps):
        make_tasks(project, 1)
        table.fail_next(422)
        result = export_tasks(tasks_qs(project), table)

        assert len(table.calls) == 1
        assert sleeps == []
        assert len(result.failed) == 1 and "422" in result.failed[0]["error"]

    def test_one_bad_record_does_not_fail_the_rest(self, project, table, sleeps):
        tasks = make_tasks(project, 15)
        bad = tasks[4]
        table.reject_keys = {str(bad.id)}
        result = export_tasks(tasks_qs(project), table)

        assert result.exported == 14
        assert [f["taskId"] for f in result.failed] == [str(bad.id)]
        assert len(table.rows) == 14 and str(bad.id) not in table.rows
        # batch 1 rejected (1 call) -> 10 single-record calls; batch 2 ok (1 call)
        assert len(table.calls) == 12

    @pytest.mark.parametrize("status", [401, 403, 404])
    def test_auth_errors_abort_the_export(self, project, table, sleeps, status):
        make_tasks(project, 25)
        table.fail_next(status)
        with pytest.raises(AirtableFatalError):
            export_tasks(tasks_qs(project), table)
        assert len(table.calls) == 1


# --------------------------------------------------------------------------- #
# Endpoint tests
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestExportEndpoint:
    @pytest.fixture(autouse=True)
    def fake_airtable(self, monkeypatch, table, sleeps):
        monkeypatch.setattr(airtable_export, "get_table", lambda: table)

    @pytest.mark.parametrize("role", ["admin", "member"])
    def test_admin_and_member_can_export(self, project, table, role):
        make_tasks(project, 5)
        client = login_as(role, project)
        response = client.post(f"/api/projects/{project.id}/export")

        assert response.status_code == 200
        assert response.data == {"total": 5, "exported": 5, "failed": []}
        assert len(table.rows) == 5

    @pytest.mark.parametrize("role", ["viewer", "outsider"])
    def test_viewer_and_non_member_get_403(self, project, table, role):
        make_tasks(project, 5)
        client = login_as(role, project)
        response = client.post(f"/api/projects/{project.id}/export")

        assert response.status_code == 403
        assert table.calls == []

    def test_second_run_creates_no_duplicates(self, project, table):
        make_tasks(project, 11)
        client = login_as("member", project)
        client.post(f"/api/projects/{project.id}/export")
        response = client.post(f"/api/projects/{project.id}/export")

        assert response.data["exported"] == 11
        assert len(table.rows) == 11

    def test_partial_failure_is_reported(self, project, table):
        tasks = make_tasks(project, 4)
        table.reject_keys = {str(tasks[2].id)}
        client = login_as("admin", project)
        response = client.post(f"/api/projects/{project.id}/export")

        assert response.status_code == 200
        assert response.data["exported"] == 3
        assert response.data["failed"][0]["taskId"] == str(tasks[2].id)

    def test_missing_credentials_returns_503(self, project, monkeypatch):
        monkeypatch.delenv("AIRTABLE_API_KEY", raising=False)
        monkeypatch.setattr(airtable_export, "get_table", REAL_GET_TABLE)
        client = login_as("admin", project)
        response = client.post(f"/api/projects/{project.id}/export")

        assert response.status_code == 503
        assert "not configured" in response.data["error"]

    def test_bad_token_returns_502(self, project, table):
        make_tasks(project, 2)
        table.fail_next(401)
        client = login_as("admin", project)
        response = client.post(f"/api/projects/{project.id}/export")
        assert response.status_code == 502

