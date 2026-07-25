"""
Management command: python manage.py run_backup [--company <id>]

Запускает резервное копирование вручную (синхронно, для отладки).
"""
from django.core.management.base import BaseCommand
from apps.backup.tasks import run_backup_task


class Command(BaseCommand):
    help = 'Run database backup manually'

    def add_arguments(self, parser):
        parser.add_argument('--company', type=int, help='Company ID (required if multiple companies)')

    def handle(self, *args, **options):
        from apps.companies.models import Company
        from apps.backup.models import BackupConfig

        company_id = options.get('company')
        if not company_id:
            configs = BackupConfig.objects.filter(is_enabled=True)
            if configs.count() == 1:
                company_id = configs.first().company_id
            else:
                self.stderr.write(self.style.ERROR('Specify --company or enable backup for only one company'))
                return

        self.stdout.write(f'Running backup for company {company_id}...')
        result = run_backup_task(company_id)
        if result == 'success':
            self.stdout.write(self.style.SUCCESS('Backup completed!'))
        else:
            self.stderr.write(self.style.ERROR(f'Backup failed: {result}'))
