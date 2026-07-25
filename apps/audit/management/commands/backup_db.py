"""
Management command to create a database backup.

Usage:
    python manage.py backup_db
"""
import os
from datetime import datetime
from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.conf import settings


class Command(BaseCommand):
    help = 'Создает резервную копию базы данных (dumpdata в JSON формат)'

    def handle(self, *args, **options):
        backup_dir = getattr(settings, 'BACKUP_DIR', os.path.join(settings.BASE_DIR, 'backups'))
        os.makedirs(backup_dir, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'skladpro_backup_{timestamp}.json'
        filepath = os.path.join(backup_dir, filename)

        self.stdout.write(f'Создание бэкапа в {filepath}...')

        with open(filepath, 'w', encoding='utf-8') as f:
            call_command(
                'dumpdata',
                stdout=f,
                indent=2,
                exclude=['contenttypes', 'auth.Permission', 'sessions']
            )

        self.stdout.write(self.style.SUCCESS(f'Резервная копия успешно создана: {filepath}'))
