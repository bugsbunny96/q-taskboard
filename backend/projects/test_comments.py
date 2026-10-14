"""Tests for task comments (Part 3a)."""
import pytest
from rest_framework.test import APIClient

from users.models import User
from projects.models import Comment, Membership, Project, Task


@pytest.fixture
def task(db):
    owner = User.objects.create_user(email="owner@example.com", name="Owner", password="password123")
    project = Project.objects.create(name="P", owner=owner)
    Membership.objects.create(user=owner, project=project, role="admin")
    return Task.objects.create(project=project, title="T", created_by=owner)


def client_for(task, role):
    user = User.objects.create_user(email=f"{role}@example.com", name=role.title(), password="password123")
    if role != "outsider":
        Membership.objects.create(user=user, project=task.project, role=role)
    client = APIClient()
    resp = client.post("/api/auth/login", {"email": user.email, "password": "password123"}, format="json")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['token']}")
    return client


def url(task):
    return f"/api/tasks/{task.id}/comments"


@pytest.mark.django_db
class TestComments:
    @pytest.mark.parametrize("role", ["admin", "member"])
    def test_admin_and_member_can_post(self, task, role):
        client = client_for(task, role)
        response = client.post(url(task), {"body": "  looks good  "}, format="json")

        assert response.status_code == 201
        assert response.data["comment"]["body"] == "looks good"
        assert response.data["comment"]["author"]["email"] == f"{role}@example.com"
        assert Comment.objects.filter(task=task).count() == 1

    def test_viewer_can_read_but_not_post(self, task):
        Comment.objects.create(task=task, author=task.created_by, body="hello")
        client = client_for(task, "viewer")

        assert client.get(url(task)).status_code == 200
        response = client.post(url(task), {"body": "sneaky"}, format="json")
        assert response.status_code == 403
        assert Comment.objects.filter(task=task).count() == 1

    def test_non_member_cannot_read_or_post(self, task):
        Comment.objects.create(task=task, author=task.created_by, body="secret")
        client = client_for(task, "outsider")

        assert client.get(url(task)).status_code == 404
        assert client.post(url(task), {"body": "hi"}, format="json").status_code == 404
        assert Comment.objects.filter(task=task).count() == 1

    def test_unauthenticated_is_rejected(self, task):
        assert APIClient().get(url(task)).status_code == 401

    def test_list_is_chronological_with_author_body_time(self, task):
        client = client_for(task, "member")
        for body in ["first", "second", "third"]:
            client.post(url(task), {"body": body}, format="json")

        comments = client.get(url(task)).data["comments"]
        assert [c["body"] for c in comments] == ["first", "second", "third"]
        assert all({"author", "body", "createdAt"} <= set(c) for c in comments)
        assert comments[0]["createdAt"] <= comments[1]["createdAt"] <= comments[2]["createdAt"]

    def test_comments_are_scoped_to_their_task(self, task):
        other = Task.objects.create(project=task.project, title="Other", created_by=task.created_by)
        Comment.objects.create(task=other, author=task.created_by, body="elsewhere")
        client = client_for(task, "member")
        assert client.get(url(task)).data["comments"] == []

    @pytest.mark.parametrize("body", ["", "   ", None, 123])
    def test_empty_or_invalid_body_is_rejected(self, task, body):
        client = client_for(task, "member")
        response = client.post(url(task), {"body": body}, format="json")
        assert response.status_code == 400
        assert Comment.objects.count() == 0

    def test_body_too_long_is_rejected(self, task):
        client = client_for(task, "member")
        response = client.post(url(task), {"body": "x" * (Comment.MAX_LENGTH + 1)}, format="json")
        assert response.status_code == 400

    @pytest.mark.parametrize("method", ["put", "patch", "delete"])
    def test_comments_are_append_only_over_http(self, task, method):
        Comment.objects.create(task=task, author=task.created_by, body="original")
        client = client_for(task, "admin")
        response = getattr(client, method)(url(task), {"body": "edited"}, format="json")

        assert response.status_code == 405
        assert Comment.objects.get(task=task).body == "original"

    def test_comments_are_append_only_in_the_model(self, task):
        comment = Comment.objects.create(task=task, author=task.created_by, body="original")
        comment.body = "edited"
        with pytest.raises(PermissionError):
            comment.save()
        with pytest.raises(PermissionError):
            comment.delete()
        assert Comment.objects.get(id=comment.id).body == "original"


@pytest.mark.django_db
class TestCommentsSurviveAsAuditTrail:
    """Comments must not disappear indirectly, e.g. through cascading deletes."""

    def test_deleting_a_task_with_comments_is_refused(self, task):
        Comment.objects.create(task=task, author=task.created_by, body="keep me")
        client = client_for(task, "member")
        response = client.delete(f"/api/tasks/{task.id}")

        assert response.status_code == 409
        assert Task.objects.filter(id=task.id).exists()
        assert Comment.objects.filter(task=task).count() == 1

    def test_deleting_a_task_without_comments_still_works(self, task):
        client = client_for(task, "member")
        assert client.delete(f"/api/tasks/{task.id}").status_code == 200
        assert not Task.objects.filter(id=task.id).exists()

    def test_deleting_a_project_with_comments_is_refused(self, task):
        Comment.objects.create(task=task, author=task.created_by, body="keep me")
        client = client_for(task, "admin")
        response = client.delete(f"/api/projects/{task.project_id}")

        assert response.status_code == 409
        assert Comment.objects.filter(task=task).count() == 1

    def test_orm_cascade_cannot_remove_comments(self, task):
        from django.db.models import ProtectedError

        Comment.objects.create(task=task, author=task.created_by, body="keep me")
        with pytest.raises(ProtectedError):
            task.delete()
        with pytest.raises(ProtectedError):
            task.created_by.delete()  # the comment's author
        assert Comment.objects.count() == 1

    def test_database_rejects_bulk_update_and_delete(self, task):
        from django.db import IntegrityError, transaction

        Comment.objects.create(task=task, author=task.created_by, body="original")
        with pytest.raises(IntegrityError), transaction.atomic():
            Comment.objects.all().update(body="tampered")
        with pytest.raises(IntegrityError), transaction.atomic():
            Comment.objects.all().delete()
        assert Comment.objects.get(task=task).body == "original"
