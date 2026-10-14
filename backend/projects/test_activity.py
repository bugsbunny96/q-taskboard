"""Tests for the project activity feed (Part 3b)."""
import pytest
from rest_framework.test import APIClient

from users.models import User
from projects import activity as activity_module
from projects.models import Activity, Comment, Membership, Project, Task


@pytest.fixture
def project(db):
    owner = User.objects.create_user(email="owner@example.com", name="Owner", password="password123")
    project = Project.objects.create(name="P", owner=owner)
    Membership.objects.create(user=owner, project=project, role="admin")
    return project


def client_for(project, role, name=None):
    user = User.objects.create_user(email=f"{role}@example.com", name=name or role.title(), password="password123")
    if role != "outsider":
        Membership.objects.create(user=user, project=project, role=role)
    client = APIClient()
    resp = client.post("/api/auth/login", {"email": user.email, "password": "password123"}, format="json")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['token']}")
    client.user = user
    return client


def feed(client, project, **params):
    return client.get(f"/api/projects/{project.id}/activity", params)


@pytest.mark.django_db
class TestActivityRecording:
    def test_all_four_events_are_recorded_with_actor(self, project):
        member = client_for(project, "member", name="Kavya")
        task_id = member.post(f"/api/projects/{project.id}/tasks", {"title": "Ship it"}, format="json").data["task"]["id"]
        member.patch(f"/api/tasks/{task_id}", {"status": "in_progress"}, format="json")
        member.patch(f"/api/tasks/{task_id}", {"assigneeId": str(member.user.id)}, format="json")
        member.post(f"/api/tasks/{task_id}/comments", {"body": "on it"}, format="json")

        items = feed(member, project).data["activity"]
        assert [a["verb"] for a in items] == ["comment_added", "assignee_changed", "status_changed", "task_created"]
        assert all(a["actor"]["name"] == "Kavya" and a["taskTitle"] == "Ship it" for a in items)
        assert items[2]["data"] == {"from": "todo", "to": "in_progress"}
        assert items[1]["data"]["to"]["name"] == "Kavya" and items[1]["data"]["from"] is None

    def test_title_only_edit_records_nothing(self, project):
        member = client_for(project, "member")
        task = Task.objects.create(project=project, title="T", created_by=project.owner)
        member.patch(f"/api/tasks/{task.id}", {"title": "Renamed", "status": "todo"}, format="json")
        assert Activity.objects.count() == 0

    def test_failed_request_records_nothing(self, project):
        viewer = client_for(project, "viewer")
        task = Task.objects.create(project=project, title="T", created_by=project.owner)
        assert viewer.patch(f"/api/tasks/{task.id}", {"status": "done"}, format="json").status_code == 403
        assert Activity.objects.count() == 0

    def test_history_survives_task_deletion(self, project):
        member = client_for(project, "member")
        task_id = member.post(f"/api/projects/{project.id}/tasks", {"title": "Temp"}, format="json").data["task"]["id"]
        assert member.delete(f"/api/tasks/{task_id}").status_code == 200

        items = feed(member, project).data["activity"]
        assert len(items) == 1 and items[0]["taskId"] is None and items[0]["taskTitle"] == "Temp"


@pytest.mark.django_db
class TestActivityIsAtomicWithTheChange:
    """Decision: if the audit write fails, the original change rolls back."""

    @pytest.fixture
    def broken_audit(self, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("activity store unavailable")
        monkeypatch.setattr(activity_module.Activity.objects, "create", boom)

    def test_task_create_rolls_back(self, project, broken_audit):
        member = client_for(project, "member")
        with pytest.raises(RuntimeError):
            member.post(f"/api/projects/{project.id}/tasks", {"title": "Ghost"}, format="json")
        assert not Task.objects.filter(title="Ghost").exists()

    def test_status_change_rolls_back(self, project, broken_audit):
        member = client_for(project, "member")
        task = Task.objects.create(project=project, title="T", created_by=project.owner)
        with pytest.raises(RuntimeError):
            member.patch(f"/api/tasks/{task.id}", {"status": "done"}, format="json")
        task.refresh_from_db()
        assert task.status == "todo"

    def test_comment_rolls_back(self, project, broken_audit):
        member = client_for(project, "member")
        task = Task.objects.create(project=project, title="T", created_by=project.owner)
        with pytest.raises(RuntimeError):
            member.post(f"/api/tasks/{task.id}/comments", {"body": "hi"}, format="json")
        assert Comment.objects.count() == 0


@pytest.mark.django_db
class TestActivityFeedAccess:
    @pytest.mark.parametrize("role", ["admin", "member", "viewer"])
    def test_members_including_viewers_can_read(self, project, role):
        client = client_for(project, role)
        assert feed(client, project).status_code == 200

    def test_non_member_gets_403(self, project):
        assert feed(client_for(project, "outsider"), project).status_code == 403

    def test_unauthenticated_gets_401(self, project):
        assert APIClient().get(f"/api/projects/{project.id}/activity").status_code == 401

    def test_feed_is_scoped_to_one_project(self, project):
        member = client_for(project, "member")
        other = Project.objects.create(name="Other", owner=project.owner)
        other_task = Task.objects.create(project=other, title="Elsewhere", created_by=project.owner)
        activity_module.record_task_created(project.owner, other_task)
        assert feed(member, project).data["activity"] == []

    def test_newest_first_and_limit(self, project):
        member = client_for(project, "member")
        for i in range(5):
            member.post(f"/api/projects/{project.id}/tasks", {"title": f"T{i}"}, format="json")
        items = feed(member, project, limit=3).data["activity"]
        assert [a["taskTitle"] for a in items] == ["T4", "T3", "T2"]
        assert feed(member, project, limit="abc").status_code == 400
