"""
Celery-задачи SaaS-подписок компаний.

Запускаются Celery Beat каждый час (PeriodicTask 'subscription-auto-freeze' и
'subscription-expiry-notify' регистрируются data-миграциями 0006/0007). Не
полагаются на «проверку при открытии страницы» — истёкшая компания блокируется
сама по себе, а о приближающемся окончании предупреждают заранее.

ЖИЗНЕННЫЙ ЦИКЛ (см. apps/companies/subscriptions.py):
    active --(end прошёл)--> grace --(льготный период прошёл)--> expired

ВАЖНО (транзакции): SELECT ... FOR UPDATE в проде Celery работает в autocommit,
поэтому выборка кандидатов обёрнута в transaction.atomic — иначе PostgreSQL
падает с TransactionManagementError («select_for_update cannot be used outside
of a transaction»). В тестах Django atomic-блоки просто вкладываются.

Гарантии задач:
- Идемпотентность: повторный запуск (в т.ч. параллельный) не создаёт
  дубликатов истории/аудита/уведомлений.
- Безопасность при параллельном запуске: строки берутся в SELECT ... FOR
  UPDATE; второй прогон после коммита первого видит уже обновлённое состояние
  и пропускает компанию (PostgreSQL возвращает текущую закоммиченную версию
  строки после ожидания блокировки).
- Tenant-safe: работают на уровне Company, без бизнес-данных компаний.
- Ручная заморозка (FROZEN) автозадачей НЕ трогается — она переводит только
  ACTIVE -> GRACE/EXPIRED и GRACE -> EXPIRED.
"""
import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .models import Company
from .subscriptions import expire_company, start_grace

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=300, name='apps.companies.tasks.auto_freeze_expired_subscriptions')
def auto_freeze_expired_subscriptions(self):
    """
    Находит компании с истёкшим сроком и переводит их в корректное состояние:

    - ACTIVE с subscription_end < now -> GRACE (бизнес продолжает работать до
      конца льготного периода) или сразу EXPIRED, если льготный период уже
      прошёл / равен нулю;
    - GRACE с истёкшим льготным периодом -> EXPIRED (бизнес-доступ блокируется).

    Данные компаний не удаляются и не меняются. Возвращает число обработанных
    компаний (для мониторинга/логов).
    """
    now = timezone.now()
    frozen_count = 0
    try:
        with transaction.atomic():
            # 1) Активные с истёкшим сроком: в льготный период или сразу expired.
            candidates = (
                Company.objects
                .filter(
                    subscription_status=Company.SubscriptionStatus.ACTIVE,
                    subscription_end__lt=now,
                )
                .select_for_update()  # сериализует параллельные запуски задачи
            )
            for company in candidates:
                # Повторная проверка после получения блокировки строки: если
                # другой экземпляр задачи уже обработал компанию — пропускаем
                # (идемпотентно).
                if company.subscription_status != Company.SubscriptionStatus.ACTIVE:
                    continue
                if company.subscription_end is None or company.subscription_end >= timezone.now():
                    continue
                grace_deadline = company.grace_end
                if grace_deadline is not None and grace_deadline > timezone.now():
                    start_grace(company)
                else:
                    expire_company(company)
                frozen_count += 1

            # 2) Льготные с истёкшим льготным периодом: в expired.
            grace_candidates = (
                Company.objects
                .filter(subscription_status=Company.SubscriptionStatus.GRACE)
                .select_for_update()
            )
            for company in grace_candidates:
                if company.subscription_status != Company.SubscriptionStatus.GRACE:
                    continue
                grace_deadline = company.grace_end
                if grace_deadline is None or grace_deadline >= timezone.now():
                    continue
                expire_company(company)
                frozen_count += 1
        if frozen_count:
            logger.info('auto_freeze_expired_subscriptions: processed %s company(ies)', frozen_count)
        return frozen_count
    except Exception:
        logger.exception('auto_freeze_expired_subscriptions failed')
        raise self.retry()


@shared_task(bind=True, max_retries=3, default_retry_delay=300, name='apps.companies.tasks.notify_subscription_expiry')
def notify_subscription_expiry(self):
    """
    Предупреждает владельца/админов компании и супер-админов о приближающемся
    окончании подписки: за 7 дней и за 1 день (колокольчик + VAPID push).

    Запускается Celery Beat каждый час (PeriodicTask 'subscription-expiry-notify'
    регистрируется data-миграцией 0007).

    Идемпотентность: на компанию создаётся не более одного уведомления каждого
    типа в течение окна (7/1 день) — повторные и параллельные запуски не
    спамят, и прочитанное уведомление не пересоздаётся. Дедупликация выполняется
    внутри той же транзакции, что и блокировка строк компании: параллельный
    прогон после ожидания блокировки видит уже созданные уведомления.

    Возвращает число отправленных уведомлений.
    """
    from datetime import timedelta

    from apps.accounts.models import User
    from apps.accounts.push_service import send_push_to_user
    from apps.messaging.models import Notification
    from apps.messaging.services import notify

    now = timezone.now()
    in_1d = now + timedelta(days=1)
    in_7d = now + timedelta(days=7)
    notified = 0
    # Push-рассылки собираем внутри транзакции, а отправляем ПОСЛЕ коммита:
    # внешние вызовы не должны держать блокировки строк компании.
    push_queue = []
    try:
        with transaction.atomic():
            candidates = Company.objects.filter(
                subscription_status=Company.SubscriptionStatus.ACTIVE,
                subscription_end__isnull=False,
                subscription_end__gt=now,
                subscription_end__lte=in_7d,
            ).select_for_update()
            for company in candidates:
                end = company.subscription_end
                if end <= in_1d:
                    alert_type = Notification.NotificationType.SUBSCRIPTION_EXPIRING
                    dedup_window = timedelta(days=1)
                else:
                    alert_type = Notification.NotificationType.SUBSCRIPTION_EXPIRING_SOON
                    dedup_window = timedelta(days=7)

                # Дедупликация по окну: уведомление этого типа по компании уже
                # создано в течение окна (независимо от прочтения) — пропускаем.
                if Notification.objects.filter(
                    company_id=company.id,
                    type=alert_type,
                    created_at__gte=now - dedup_window,
                ).exists():
                    continue

                end_text = end.strftime('%d.%m.%Y')
                recipients = list(User.objects.filter(
                    company_id=company.id,
                    is_active=True,
                    role__in=(User.Role.OWNER, User.Role.ADMIN),
                ))
                recipients += list(User.objects.filter(
                    is_active=True,
                    role=User.Role.SUPERADMIN,
                ))

                notify(
                    recipients,
                    alert_type,
                    company.name,
                    f'{company.name} — {end_text}',
                    company=company,
                )
                for user in recipients:
                    push_queue.append((
                        user,
                        company.name,
                        f'Подписка истекает {end_text}',
                        '/#/companies' if user.is_superadmin else '/#/',
                    ))
                notified += len(recipients)

        for user, title, body, url in push_queue:
            send_push_to_user(user, title, body, data={'url': url})
        if notified:
            logger.info('notify_subscription_expiry: %s notification(s) sent', notified)
        return notified
    except Exception:
        logger.exception('notify_subscription_expiry failed')
        raise self.retry()
