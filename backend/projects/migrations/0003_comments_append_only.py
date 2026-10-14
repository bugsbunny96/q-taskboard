import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

# Database-level guarantee that comments are append-only. Row-level UPDATE and
# DELETE are rejected; INSERT is allowed. TRUNCATE is intentionally not blocked so
# an operator can still reset a dev database on purpose (manage.py reset_audit_trail).
CREATE_TRIGGER = """
CREATE OR REPLACE FUNCTION comments_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'comments are append-only: % is not allowed', TG_OP
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER comments_no_update_or_delete
    BEFORE UPDATE OR DELETE ON comments
    FOR EACH ROW EXECUTE FUNCTION comments_append_only();
"""

DROP_TRIGGER = """
DROP TRIGGER IF EXISTS comments_no_update_or_delete ON comments;
DROP FUNCTION IF EXISTS comments_append_only();
"""


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0002_comment'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='comment',
            name='task',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='comments', to='projects.task'),
        ),
        migrations.AlterField(
            model_name='comment',
            name='author',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='comments', to=settings.AUTH_USER_MODEL),
        ),
        migrations.RunSQL(CREATE_TRIGGER, DROP_TRIGGER),
    ]
