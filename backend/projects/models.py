import uuid
from django.db import models
from django.conf import settings


class Project(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, null=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='owned_projects')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'projects'


class Membership(models.Model):
    ROLE_CHOICES = [('admin', 'Admin'), ('member', 'Member'), ('viewer', 'Viewer')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='memberships')
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='memberships')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='member')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'memberships'
        unique_together = ('user', 'project')


class Task(models.Model):
    STATUS_CHOICES = [
        ('todo', 'To Do'),
        ('in_progress', 'In Progress'),
        ('review', 'Review'),
        ('done', 'Done'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='tasks')
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='todo')
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='assigned_tasks',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='created_tasks',
    )
    position = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tasks'
        indexes = [models.Index(fields=['project', 'status'])]


class Comment(models.Model):
    """A comment on a task. Append-only, because comments are part of the engagement
    audit trail. Enforced in three layers:

    1. API: only list + create endpoints exist (PUT/PATCH/DELETE -> 405).
    2. ORM: save()/delete() refuse to touch an existing row, and the foreign keys are
       PROTECT, so deleting a task, project or user that has comments raises instead
       of silently cascading the comments away.
    3. Database: a Postgres trigger (migration 0003) rejects UPDATE/DELETE on the
       comments table, covering bulk queryset operations and raw SQL.
    """

    MAX_LENGTH = 5000

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.PROTECT, related_name='comments')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='comments')
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'comments'
        ordering = ['created_at', 'id']
        indexes = [models.Index(fields=['task', 'created_at'], name='comments_task_id_created_idx')]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError('comments are append-only and cannot be edited')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError('comments are append-only and cannot be deleted')
