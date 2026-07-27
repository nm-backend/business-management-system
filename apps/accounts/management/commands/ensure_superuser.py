"""
Создаёт платформенного супер-администратора при первом запуске (bootstrap).

Зачем: на PaaS (Railway, Render) нет интерактивной консоли, а
`manage.py createsuperuser` требует ввода. Без первого супер-админа некому
войти в /admin/ и выдать сотрудникам коды доступа.

Как пользоваться:
  1. Задать переменные окружения сервиса (пароль задаёте ВЫ, он не хранится в коде):
        DJANGO_SUPERUSER_USERNAME=<логин>
        DJANGO_SUPERUSER_PASSWORD=<пароль>
        DJANGO_SUPERUSER_FULL_NAME=<имя>        (необязательно)
  2. Команда выполняется при деплое (pre-deploy) или вручную.
  3. После первого входа переменную с паролем можно удалить.

Идемпотентна: если супер-админ уже есть или переменные не заданы — просто
сообщает об этом и выходит с кодом 0, поэтому её безопасно вызывать на каждом
деплое (в отличие от createsuperuser --noinput, который падает на дубликате).
"""
import os

from django.core.management.base import BaseCommand

from apps.accounts.models import User


class Command(BaseCommand):
    help = ('Создаёт супер-администратора из DJANGO_SUPERUSER_* переменных, '
            'если в системе ещё нет ни одного. Идемпотентна.')

    def handle(self, *args, **options):
        if User.objects.filter(role=User.Role.SUPERADMIN).exists():
            self.stdout.write('Супер-администратор уже существует — пропускаю.')
            return

        username = (os.environ.get('DJANGO_SUPERUSER_USERNAME') or '').strip()
        password = os.environ.get('DJANGO_SUPERUSER_PASSWORD') or ''
        full_name = (os.environ.get('DJANGO_SUPERUSER_FULL_NAME') or '').strip()

        if not username or not password:
            self.stdout.write(
                'DJANGO_SUPERUSER_USERNAME / DJANGO_SUPERUSER_PASSWORD не заданы — '
                'супер-администратор не создан.'
            )
            return

        if User.objects.filter(username=username).exists():
            self.stdout.write(f'Пользователь «{username}» уже есть — пропускаю.')
            return

        # create_superuser сам ставит role=superadmin, is_staff и is_superuser.
        User.objects.create_superuser(username=username, password=password,
                                      full_name=full_name)
        self.stdout.write(self.style.SUCCESS(
            f'Супер-администратор «{username}» создан. Войдите и удалите '
            f'переменную DJANGO_SUPERUSER_PASSWORD.'
        ))
