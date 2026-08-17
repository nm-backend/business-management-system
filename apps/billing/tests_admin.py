"""
Админка подписок: дашборд и быстрое продление одним кликом.

Дашборд доступен только персоналу (супер-админу), показывает истекающие
и замороженные компании; quick-extend — только POST, продлевает активную
(+30 от текущего срока) и активирует замороженную (свежий период).
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.companies.models import Company

from .models import Subscription
from .services import freeze_subscription

DASHBOARD_URL = '/admin/billing/subscription/dashboard/'


class SubscriptionAdminDashboardTests(TestCase):
    def setUp(self):
        self.sa = User.objects.create_superuser(username='root', password='pw12345X')
        self.company = Company.objects.create(name='DashCo')
        self.sub = Subscription.objects.get(company=self.company)
        self.client.force_login(self.sa)

    def test_dashboard_shows_stats_and_company(self):
        # Подписка, истекающая в ближайшие 7 дней, попадает в таблицу дашборда.
        Subscription.objects.filter(pk=self.sub.pk).update(
            expires_at=timezone.now() + timedelta(days=2),
        )
        resp = self.client.get(DASHBOARD_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'DashCo')
        self.assertContains(resp, 'Дашборд подписок')
        self.assertContains(resp, 'Продлить +30 дней')

    def test_dashboard_lists_frozen_companies(self):
        Subscription.objects.filter(pk=self.sub.pk).update(
            expires_at=timezone.now() - timedelta(days=1),
        )
        self.sub.refresh_from_db()
        freeze_subscription(self.sub)
        resp = self.client.get(DASHBOARD_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'DashCo')
        self.assertContains(resp, 'Активировать +30 дней')

    def test_dashboard_requires_staff(self):
        self.client.logout()
        resp = self.client.get(DASHBOARD_URL)
        # Персона не залогинена — редирект на логин.
        self.assertEqual(resp.status_code, 302)

    def test_quick_extend_active_subscription_by_one_click(self):
        before = self.sub.expires_at
        resp = self.client.post(f'/admin/billing/subscription/quick-extend/{self.sub.pk}/')
        self.assertRedirects(resp, DASHBOARD_URL)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.ACTIVE)
        # От max(now, expires_at): оставшиеся дни не сгорают.
        self.assertGreater(self.sub.expires_at, before + timedelta(days=29))
        # Событие «продлена супер-админом» в истории.
        from .models import SubscriptionEvent
        self.assertTrue(
            SubscriptionEvent.objects.filter(
                subscription=self.sub, action=SubscriptionEvent.Action.EXTENDED,
            ).exists(),
        )

    def test_quick_extend_activates_frozen_subscription(self):
        Subscription.objects.filter(pk=self.sub.pk).update(
            expires_at=timezone.now() - timedelta(days=1),
        )
        self.sub.refresh_from_db()
        self.assertTrue(freeze_subscription(self.sub))
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.FROZEN)

        resp = self.client.post(f'/admin/billing/subscription/quick-extend/{self.sub.pk}/')
        self.assertRedirects(resp, DASHBOARD_URL)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.ACTIVE)
        self.assertFalse(self.sub.is_blocked)
        self.assertIsNone(self.sub.frozen_at)

    def test_dashboard_shows_gray_zone_expired_company(self):
        """
        «Серая зона»: статус ещё active, но срок уже прошёл (истечение между
        прогонами Celery). Компания уже заблокирована gate — дашборд обязан
        показать её в таблице замороженных, а не считать «активной».
        """
        Subscription.objects.filter(pk=self.sub.pk).update(
            expires_at=timezone.now() - timedelta(hours=2),
        )
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.ACTIVE)
        self.assertTrue(self.sub.is_blocked)

        resp = self.client.get(DASHBOARD_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'DashCo')
        self.assertContains(resp, 'Активировать +30 дней')
        # Статистика: 0 активных, 1 заблокирована.
        self.assertContains(resp, '>0<', html=False)
        self.assertContains(resp, '>1<', html=False)

    def test_quick_extend_activates_gray_zone_subscription(self):
        """Продление «серой зоны» даёт свежий период (событие activated)."""
        Subscription.objects.filter(pk=self.sub.pk).update(
            expires_at=timezone.now() - timedelta(hours=2),
        )
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.ACTIVE)
        self.assertTrue(self.sub.is_blocked)

        resp = self.client.post(f'/admin/billing/subscription/quick-extend/{self.sub.pk}/')
        self.assertRedirects(resp, DASHBOARD_URL)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.ACTIVE)
        self.assertFalse(self.sub.is_blocked)
        from .models import SubscriptionEvent
        self.assertTrue(
            SubscriptionEvent.objects.filter(
                subscription=self.sub, action=SubscriptionEvent.Action.ACTIVATED,
            ).exists(),
        )

    def test_quick_extend_get_is_redirected(self):
        resp = self.client.get(f'/admin/billing/subscription/quick-extend/{self.sub.pk}/')
        self.assertRedirects(resp, DASHBOARD_URL)
        # GET ничего не меняет.
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.ACTIVE)

    def test_quick_extend_unknown_subscription_is_404(self):
        resp = self.client.post('/admin/billing/subscription/quick-extend/999999/')
        self.assertEqual(resp.status_code, 404)
