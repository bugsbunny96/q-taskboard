"""Helpers for writing audit records. Callers must invoke these inside the same
``transaction.atomic()`` block as the change being recorded."""
from .models import Activity


def _user_ref(user):
    return {'id': str(user.id), 'name': user.name} if user else None


def record(actor, verb, task, data=None):
    return Activity.objects.create(
        project_id=task.project_id,
        actor=actor,
        verb=verb,
        task=task,
        task_title=task.title,
        data=data or {},
    )


def record_task_created(actor, task):
    return record(actor, Activity.TASK_CREATED, task, {'status': task.status})


def record_status_changed(actor, task, old, new):
    return record(actor, Activity.STATUS_CHANGED, task, {'from': old, 'to': new})


def record_assignee_changed(actor, task, old_user, new_user):
    return record(actor, Activity.ASSIGNEE_CHANGED, task,
                  {'from': _user_ref(old_user), 'to': _user_ref(new_user)})


def record_comment_added(actor, task, comment):
    return record(actor, Activity.COMMENT_ADDED, task, {'commentId': str(comment.id)})
