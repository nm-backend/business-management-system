"""
Гонки жизненного цикла подписки (только PostgreSQL: на SQLite
select_for_update не блокирует — см. apps/core/tests_race.py).

  - freeze (Celery) против renew (оплата) — без потерянного обновления:
    итог всегда консистентен (renew побеждает, либо freeze успел и затем
    renew возвращает в active);
  - параллельные продления — ровно один pending-счёт (без дубликатов).
"""
from datetime import timedelta

from django.test import TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone

from apps.accounts.models import User
from apps.companies.models import Company
from apps.core.tests_race import run_parallel

from .models import Invoice, Subscription, SubscriptionEvent
from .services import (
    create_invoice, freeze_subscription, quick_renew_subscription, renew_subscription,
)


@skipUnlessDBFeature('has_select_for_update')
class SubscriptionRaceTests(TransactionTestCase):
    reset_sequences = False

    def setUp(self):
        self.company = Company.objects.create(name='RaceSubCo')
        self.owner = User.objects.create_user(
            username='rs_o', password='pw', role=User.Role.OWNER, company=self.company,
        )
        self.sub = Subscription.objects.get(company=self.company)

    def _expire(self):
        Subscription.objects.filter(pk=self.sub.pk).update(
            expires_at=timezone.now() - timedelta(days=1),
        )

    def test_freeze_vs_renew_no_lost_update(self):
        """
        Параллельные freeze и renew одной подписки.

        Без блокировки строки возможен потерянный сценарий: freeze читает
        «active, истекла» и пишет frozen, renew одновременно пишет active —
        итог зависит от порядка коммитов, и одно из действий «пропадает».
        С select_for_update оба сериализуются; итог консистентен:
          - renew первый → freeze повторно проверяет срок и пропускает;
          - freeze первый → renew возвращает компанию в active.
        В любом случае: статус ACTIVE, срок в будущем, ровно одно renew-событие.
        """
        self._expire()
        results = run_parallel(
            lambda i: (
                freeze_subscription(self.sub) if i % 2 == 0
                else renew_subscription(self.sub, actor=self.owner)
            ),
            n=8,
        )
        self.assertFalse(
            [r for r in results if isinstance(r, str) and r.startswith('EXC:')],
            f'Исключения в гонке: {results}',
        )
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.ACTIVE)
        self.assertGreater(self.sub.expires_at, timezone.now() + timedelta(days=29))
        self.assertIsNone(self.sub.frozen_at)
        self.assertEqual(
            SubscriptionEvent.objects.filter(
                subscription=self.sub, action='renewed',
            ).count(),
            1,
            'Двойное продление — событие renewed должно быть ровно одно',
        )

    def test_concurrent_renew_creates_single_pending_invoice(self):
        """8 параллельных «Продлить» → ровно один pending-счёт."""
        run_parallel(
            lambda i: create_invoice(self.sub, actor=self.owner)[0].pk,
            n=8,
        )
        pending = Invoice.objects.filter(
            subscription=self.sub, status=Invoice.Status.PENDING,
        )
        self.assertEqual(pending.count(), 1, 'Должен быть ровно один pending-счёт')

    def test_concurrent_freeze_is_idempotent(self):
        """8 параллельных заморозок истёкшей подписки → одно frozen-событие."""
        self._expire()
        run_parallel(lambda i: freeze_subscription(self.sub), n=8)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.FROZEN)
        self.assertEqual(
            SubscriptionEvent.objects.filter(
                subscription=self.sub, action='frozen',
            ).count(),
            1,
        )

    def test_quick_renew_vs_freeze_no_lost_update(self):
        """
        Гонка «быстрое продление из админки» против Celery-заморозки.

        Раньше выбор «активировать/продлить» делался в view по is_blocked ВНЕ
        блокировки строки — между чтением и записью могла вклиниться заморозка,
        и итог зависел от порядка коммитов. Теперь quick_renew_subscription
        решает ПОД select_for_update; оба исхода консистентны:
          - renew первый → freeze повторно проверяет срок и пропускает;
          - freeze первый → quick_renew видит заморозку и активирует.
        В любом случае: статус ACTIVE, срок в будущем, ровно ОДНО событие
        продления (activated; extended невозможен — подписка истекла) и
        ноль потерянных обновлений.
        """
        self._expire()
        results = run_parallel(
            lambda i: (
                freeze_subscription(self.sub) if i % 2 == 0
                else quick_renew_subscription(self.sub, actor=self.owner)
            ),
            n=2,
        )
        self.assertFalse(
            [r for r in results if isinstance(r, str) and r.startswith('EXC:')],
            f'Исключения в гонке: {results}',
        )
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.ACTIVE)
        self.assertGreater(self.sub.expires_at, timezone.now() + timedelta(days=29))
        self.assertIsNone(self.sub.frozen_at)
        events = list(
            SubscriptionEvent.objects.filter(subscription=self.sub)
            .values_list('action', flat=True)
        )
        self.assertEqual(
            events.count('activated'), 1,
            f'Продление должно сработать ровно один раз: {events}',
        )
        self.assertEqual(
            events.count('extended'), 0,
            'Подписка истекла — quick_renew обязан активировать, а не продлевать',
        )
        self.assertLessEqual(
            events.count('frozen'), 1,
            f'Заморозка возможна максимум один раз: {events}',
        )

    def test_concurrent_quick_renew_accumulates_days(self):
        """
        8 параллельных quick_renew без гонки: ни одно продление не теряется
        (lost update) — срок растёт на 8×30 дней, событий ровно 8.
        """
        self._expire()
        results = run_parallel(
            lambda i: quick_renew_subscription(self.sub, actor=self.owner)[0].pk,
            n=8,
        )
        self.assertFalse(
            [r for r in results if isinstance(r, str) and r.startswith('EXC:')],
            f'Исключения в гонке: {results}',
        )
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.ACTIVE)
        # Первый активирует (свежие 30 дней), остальные 7 продлевают +30
        # от текущего срока → суммарно ~240 дней, ничего не потеряно.
        self.assertGreater(
            self.sub.expires_at, timezone.now() + timedelta(days=239),
            f'Потеряно продление: expires_at={self.sub.expires_at}',
        )
        events = list(
            SubscriptionEvent.objects.filter(subscription=self.sub)
            .values_list('action', flat=True)
        )
        self.assertEqual(events.count('activated'), 1, events)
        self.assertEqual(events.count('extended'), 7, events)
