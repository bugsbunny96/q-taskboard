import uuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0003_comments_append_only'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Activity',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('verb', models.CharField(choices=[('task_created', 'Task created'), ('status_changed', 'Status changed'), ('assignee_changed', 'Assignee changed'), ('comment_added', 'Comment added')], max_length=32)),
                ('task_title', models.CharField(max_length=500)),
                ('data', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('actor', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='activities', to=settings.AUTH_USER_MODEL)),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='activities', to='projects.project')),
                ('task', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='activities', to='projects.task')),
            ],
            options={
                'db_table': 'activities',
                'ordering': ['-created_at', '-id'],
                'indexes': [models.Index(fields=['project', '-created_at'], name='activity_project_created_idx')],
            },
        ),
    ]
