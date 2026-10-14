from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = (
        "DEV ONLY: permanently erase the audit trail (task comments) so `seed` can "
        "rebuild the database. Comments are append-only, so this is deliberately a "
        "separate, explicit step that requires --yes."
    )

    def add_arguments(self, parser):
        parser.add_argument('--yes', action='store_true', help='confirm the irreversible erase')

    def handle(self, *args, **options):
        if not options['yes']:
            raise CommandError('refusing to erase the audit trail without --yes')
        with connection.cursor() as cursor:
            cursor.execute('TRUNCATE TABLE comments')
        self.stdout.write(self.style.WARNING('audit trail erased (comments truncated)'))
