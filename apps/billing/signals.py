"""
Сигналы: авто-провижининг подписки при создании компании.

Каждая новая компания получает подписку на 30 дней (SUBSCRIPTION_DAYS)
сразу при создании — через какой бы путь она ни создавалась (API, админка,
тесты). Ошибка провижининга роняет создание компании целиком: компания без
подписки была бы навсегда заморожена subscription gate (fail-closed), что
хуже, чем не создать компанию вовсе.

Бэкфилл для уже существующих компаний — в data-миграции 0002 (миграции
не стреляют сигналами).
"""
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(post_save, sender='companies.Company')
def provision_subscription(sender, instance, created, **kwargs):
    if not created:
        return
    from .services import create_subscription
    # Без try/except: см. docstring — fail-closed хуже, чем rollback создания.
    create_subscription(instance)
