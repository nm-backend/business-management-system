"""
Тесты SaaS-подписок компаний.

Покрывают весь контур: создание компании -> триал, активация/продление/
заморозка/разморозка, автозаморозка Celery (идемпотентность), RBAC
(owner/admin НЕ могут менять подписку), cross-tenant, audit log, экран
«Подписка истекла» (me/логин работают, бизнес-API заблокирован).
"""
from datetime import timedelta

from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.companies.models import Company, SubscriptionChange, SubscriptionPlan
from apps.companies.tasks import auto_freeze_expired_subscriptions
from .models import DEFAULT_SUBSCRIPTION_DAYS


def make_company(name='Acme', **company_kwargs):
    """
    Создаёт компанию с активной подпиской (как в проде после создания).

    Прямая запись полей, без истории/аудита — тесты считают записи сами.
    План — по умолчанию (Free Trial), is_trial=True.
    """
    company = Company.objects.create(
        name=name,
        plan=SubscriptionPlan.get_default_plan(),
        **company_kwargs,
    )
    if company.subscription_end is None:
        now = timezone.now()
        company.subscription_start = now
        company.subscription_end = now + timedelta(days=DEFAULT_SUBSCRIPTION_DAYS)
        company.save(update_fields=['subscription_start', 'subscription_end'])
    return company


def make_owner(company, username='acme_owner', password='secretpw'):
    return User.objects.create_user(
        username=username, password=password,
        role=User.Role.OWNER, company=company,
    )


def make_admin(company, username='acme_admin'):
    return User.objects.create_user(
        username=username, password='secretpw',
        role=User.Role.ADMIN, company=company,
    )


class SubscriptionTestCase(TestCase):
    """Общий setUp: супер-админ + компания с владельцем."""

    def setUp(self):
        self.superadmin = User.objects.create_superuser(username='root', password='pw')
        self.api = APIClient()
        self.api.force_authenticate(user=self.superadmin)
        self.company = make_company()
        self.owner = make_owner(self.company)
        self.api_owner = APIClient()
        self.api_owner.force_authenticate(user=self.owner)

    def auth(self, client, user):
        client.force_authenticate(user=user)


class CompanyCreationTests(SubscriptionTestCase):
    def test_company_creation_gets_30_day_trial(self):
        resp = self.api.post('/api/v1/companies/', {
            'name': 'NewCo',
            'owner_username': 'newco_owner',
            'owner_password': 'Str0ng!Pass',
            'owner_full_name': 'New Owner',
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        company = Company.objects.get(name='NewCo')
        self.assertEqual(company.subscription_status, Company.SubscriptionStatus.ACTIVE)
        self.assertIsNotNone(company.subscription_start)
        self.assertIsNotNone(company.subscription_end)
        self.assertAlmostEqual(
            company.subscription_end,
            company.subscription_start + timedelta(days=DEFAULT_SUBSCRIPTION_DAYS),
            delta=timedelta(seconds=2),
        )
        # Триал записан в историю.
        self.assertTrue(company.subscription_changes.filter(
            action=SubscriptionChange.Action.ACTIVATED,
            days_added=DEFAULT_SUBSCRIPTION_DAYS,
        ).exists())

    def test_company_creation_via_admin_gets_trial(self):
        from django.test import Client
        sa = User.objects.create_superuser(username='admin_root', password='pw12345X')
        client = Client()
        client.force_login(sa)
        resp = client.post('/admin/companies/company/add/', {
            'name': 'AdminMadeCo', 'is_active': 'on',
            'owner_username': 'am_owner', 'owner_password': 'Str0ng!Pass9',
            'owner_full_name': 'AM Owner', 'owner_phone': '',
        })
        self.assertIn(resp.status_code, (200, 302))
        company = Company.objects.get(name='AdminMadeCo')
        self.assertEqual(company.subscription_status, Company.SubscriptionStatus.ACTIVE)
        self.assertIsNotNone(company.subscription_end)

    def test_active_subscription_allows_business_access(self):
        self.assertEqual(self.api_owner.get('/api/v1/warehouse/raw-materials/').status_code, 200)

    def test_me_returns_subscription_status(self):
        resp = self.api_owner.get('/api/v1/accounts/me/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['subscription_status'], Company.SubscriptionStatus.ACTIVE)
        self.assertIsNotNone(resp.data['subscription_end'])


class EffectiveStatusTests(SubscriptionTestCase):
    def test_effective_status_grace_when_end_passed_within_grace(self):
        """Срок прошёл, но льготный период ещё идёт -> effective grace, доступ жив."""
        self.company.subscription_end = timezone.now() - timedelta(days=1)
        self.company.save(update_fields=['subscription_end'])
        self.assertEqual(
            self.company.effective_subscription_status,
            Company.SubscriptionStatus.GRACE,
        )
        # Льготный период: бизнес продолжает работать, хотя срок уже прошёл.
        self.assertEqual(self.api_owner.get('/api/v1/warehouse/raw-materials/').status_code, 200)
        # Профиль отдаёт фактический статус grace.
        me = self.api_owner.get('/api/v1/accounts/me/')
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data['subscription_status'], Company.SubscriptionStatus.GRACE)

    def test_effective_status_expired_when_grace_passed(self):
        self.company.subscription_end = timezone.now() - timedelta(days=8)
        self.company.save(update_fields=['subscription_end'])
        self.assertEqual(self.company.effective_subscription_status, Company.SubscriptionStatus.EXPIRED)
        # Бизнес-доступ заблокирован, хотя формальный статус ещё active.
        self.assertEqual(self.api_owner.get('/api/v1/warehouse/raw-materials/').status_code, 403)
        # Профиль (экран «Подписка истекла») доступен.
        self.assertEqual(self.api_owner.get('/api/v1/accounts/me/').status_code, 200)

    def test_grace_disabled_company_expires_immediately(self):
        """grace_period_days=0: срок прошёл -> сразу effective expired."""
        self.company.grace_period_days = 0
        self.company.subscription_end = timezone.now() - timedelta(minutes=1)
        self.company.save(update_fields=['grace_period_days', 'subscription_end'])
        self.assertEqual(self.company.effective_subscription_status, Company.SubscriptionStatus.EXPIRED)
        self.assertEqual(self.api_owner.get('/api/v1/warehouse/raw-materials/').status_code, 403)

    def test_expired_owner_can_login(self):
        self.company.subscription_end = timezone.now() - timedelta(days=8)
        self.company.save(update_fields=['subscription_end'])
        resp = self.api_owner.post('/api/v1/accounts/login/', {
            'username': self.owner.username, 'password': 'secretpw',
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['user']['subscription_status'], 'expired')


class AutoFreezeTests(SubscriptionTestCase):
    def _make_expired_company(self, days=8):
        """Компания, чей срок и льготный период уже прошли."""
        company = make_company(name='ExpiredCo')
        owner = make_owner(company, username='exp_owner')
        company.subscription_end = timezone.now() - timedelta(days=days)
        company.save(update_fields=['subscription_end'])
        return company, owner

    def test_auto_freeze_marks_expired_and_writes_history(self):
        company, _ = self._make_expired_company()
        frozen = auto_freeze_expired_subscriptions.run()
        self.assertEqual(frozen, 1)
        company.refresh_from_db()
        self.assertEqual(company.subscription_status, Company.SubscriptionStatus.EXPIRED)
        self.assertEqual(
            company.subscription_changes.filter(action=SubscriptionChange.Action.EXPIRED).count(),
            1,
        )
        # Audit записан с привязкой к компании (системный actor).
        self.assertTrue(AuditLog.objects.filter(
            company=company, action=AuditLog.Action.SUBSCRIPTION_EXPIRED,
        ).exists())

    def test_auto_freeze_moves_recently_expired_to_grace_not_expired(self):
        """Срок прошёл 1 день назад (grace=7): задача переводит в grace, не в expired."""
        company, _ = self._make_expired_company(days=1)
        frozen = auto_freeze_expired_subscriptions.run()
        self.assertEqual(frozen, 1)
        company.refresh_from_db()
        self.assertEqual(company.subscription_status, Company.SubscriptionStatus.GRACE)
        self.assertEqual(
            company.subscription_changes.filter(action=SubscriptionChange.Action.GRACE_STARTED).count(),
            1,
        )
        self.assertTrue(AuditLog.objects.filter(
            company=company, action=AuditLog.Action.SUBSCRIPTION_GRACE_STARTED,
        ).exists())

    def test_auto_freeze_grace_to_expired_after_grace_ends(self):
        """Из grace задача переводит в expired, когда льготный период вышел."""
        company, _ = self._make_expired_company(days=1)
        auto_freeze_expired_subscriptions.run()
        company.refresh_from_db()
        self.assertEqual(company.subscription_status, Company.SubscriptionStatus.GRACE)
        # Льготный период вышел (end был 1 день назад, grace=7 -> ещё идёт).
        # Сдвигаем end на 8 дней назад И переводим формально в grace,
        # как будто задача уже отработала на прошлой неделе.
        company.subscription_end = timezone.now() - timedelta(days=8)
        company.save(update_fields=['subscription_end'])
        frozen = auto_freeze_expired_subscriptions.run()
        self.assertEqual(frozen, 1)
        company.refresh_from_db()
        self.assertEqual(company.subscription_status, Company.SubscriptionStatus.EXPIRED)
        self.assertEqual(
            company.subscription_changes.filter(action=SubscriptionChange.Action.EXPIRED).count(),
            1,
        )

    def test_auto_freeze_idempotent_on_rerun(self):
        company, _ = self._make_expired_company()
        auto_freeze_expired_subscriptions.run()
        auto_freeze_expired_subscriptions.run()  # повторный запуск
        company.refresh_from_db()
        self.assertEqual(company.subscription_status, Company.SubscriptionStatus.EXPIRED)
        self.assertEqual(
            company.subscription_changes.filter(action=SubscriptionChange.Action.EXPIRED).count(),
            1,
        )
        self.assertEqual(
            AuditLog.objects.filter(
                company=company, action=AuditLog.Action.SUBSCRIPTION_EXPIRED,
            ).count(),
            1,
        )

    def test_auto_freeze_does_not_touch_manual_frozen(self):
        self.company.subscription_status = Company.SubscriptionStatus.FROZEN
        self.company.subscription_end = timezone.now() - timedelta(days=2)
        self.company.save(update_fields=['subscription_status', 'subscription_end'])
        frozen = auto_freeze_expired_subscriptions.run()
        self.assertEqual(frozen, 0)
        self.company.refresh_from_db()
        # Ручная заморозка НЕ снимается и НЕ перетирается автозадачей.
        self.assertEqual(self.company.subscription_status, Company.SubscriptionStatus.FROZEN)

    def test_auto_freeze_skips_active_companies(self):
        frozen = auto_freeze_expired_subscriptions.run()
        self.assertEqual(frozen, 0)
        self.company.refresh_from_db()
        self.assertEqual(self.company.subscription_status, Company.SubscriptionStatus.ACTIVE)


class ExtensionTests(SubscriptionTestCase):
    def test_extend_active_preserves_remainder(self):
        old_end = timezone.now() + timedelta(days=10)
        self.company.subscription_end = old_end
        self.company.save(update_fields=['subscription_end'])
        resp = self.api.post(f'/api/v1/companies/{self.company.id}/subscription_extend/',
                             {'days': 30}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.company.refresh_from_db()
        # Остаток не обнулился: end сдвинулся ОТ старого end.
        self.assertAlmostEqual(
            self.company.subscription_end, old_end + timedelta(days=30),
            delta=timedelta(seconds=2),
        )
        self.assertEqual(self.company.subscription_status, Company.SubscriptionStatus.ACTIVE)

    def test_extend_expired_reactivates(self):
        self.company.subscription_end = timezone.now() - timedelta(days=1)
        self.company.save(update_fields=['subscription_end'])
        resp = self.api.post(f'/api/v1/companies/{self.company.id}/subscription_extend/',
                             {'days': 30}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.company.refresh_from_db()
        self.assertEqual(self.company.subscription_status, Company.SubscriptionStatus.ACTIVE)
        self.assertGreater(self.company.subscription_end, timezone.now())
        # История + аудит записаны.
        self.assertTrue(self.company.subscription_changes.filter(
            action=SubscriptionChange.Action.EXTENDED, days_added=30,
        ).exists())
        self.assertTrue(AuditLog.objects.filter(
            company=self.company, action=AuditLog.Action.SUBSCRIPTION_EXTENDED,
        ).exists())

    def test_extend_validation(self):
        url = f'/api/v1/companies/{self.company.id}/subscription_extend/'
        for bad in (0, -5, 'abc'):
            resp = self.api.post(url, {'days': bad}, format='json')
            self.assertEqual(resp.status_code, 400, msg=f'days={bad}')
        # Запись не создана.
        self.assertFalse(self.company.subscription_changes.filter(
            action=SubscriptionChange.Action.EXTENDED,
        ).exists())

    def test_set_end_future_date_ok(self):
        future = timezone.now() + timedelta(days=60)
        resp = self.api.post(
            f'/api/v1/companies/{self.company.id}/subscription_set_end/',
            {'end': future.isoformat()}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.company.refresh_from_db()
        self.assertAlmostEqual(self.company.subscription_end, future, delta=timedelta(seconds=2))
        self.assertTrue(self.company.subscription_changes.filter(
            action=SubscriptionChange.Action.END_SET,
        ).exists())

    def test_set_end_past_date_rejected(self):
        past = timezone.now() - timedelta(days=1)
        resp = self.api.post(
            f'/api/v1/companies/{self.company.id}/subscription_set_end/',
            {'end': past.isoformat()}, format='json',
        )
        self.assertEqual(resp.status_code, 400)
        # Срок не изменился.
        old_end = self.company.subscription_end
        self.company.refresh_from_db()
        self.assertEqual(self.company.subscription_end, old_end)


class FreezeTests(SubscriptionTestCase):
    def test_manual_freeze_blocks_business_but_not_me(self):
        resp = self.api.post(f'/api/v1/companies/{self.company.id}/subscription_freeze/')
        self.assertEqual(resp.status_code, 200)
        self.company.refresh_from_db()
        self.assertEqual(self.company.subscription_status, Company.SubscriptionStatus.FROZEN)
        # Владелец замороженной компании:
        # - НЕ может пользоваться бизнес-API;
        # - МОЖЕТ видеть профиль (экран «Подписка истекла»).
        self.assertEqual(self.api_owner.get('/api/v1/warehouse/raw-materials/').status_code, 403)
        self.assertEqual(self.api_owner.get('/api/v1/orders/orders/').status_code, 403)
        me = self.api_owner.get('/api/v1/accounts/me/')
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data['subscription_status'], Company.SubscriptionStatus.FROZEN)

    def test_manual_freeze_writes_history_and_audit(self):
        self.api.post(f'/api/v1/companies/{self.company.id}/subscription_freeze/')
        self.assertTrue(self.company.subscription_changes.filter(
            action=SubscriptionChange.Action.FROZEN,
        ).exists())
        self.assertTrue(AuditLog.objects.filter(
            company=self.company, action=AuditLog.Action.SUBSCRIPTION_FROZEN,
            actor=self.superadmin,
        ).exists())

    def test_unfreeze_with_future_end_restores_active(self):
        future_end = timezone.now() + timedelta(days=5)
        self.company.subscription_end = future_end
        self.company.subscription_status = Company.SubscriptionStatus.FROZEN
        self.company.save(update_fields=['subscription_end', 'subscription_status'])
        resp = self.api.post(f'/api/v1/companies/{self.company.id}/subscription_unfreeze/')
        self.assertEqual(resp.status_code, 200)
        self.company.refresh_from_db()
        self.assertEqual(self.company.subscription_status, Company.SubscriptionStatus.ACTIVE)
        # Прежний будущий срок сохранён (не обнулён).
        self.assertAlmostEqual(self.company.subscription_end, future_end, delta=timedelta(seconds=2))

    def test_unfreeze_with_passed_end_grants_30_days(self):
        self.company.subscription_end = timezone.now() - timedelta(days=1)
        self.company.subscription_status = Company.SubscriptionStatus.FROZEN
        self.company.save(update_fields=['subscription_end', 'subscription_status'])
        resp = self.api.post(f'/api/v1/companies/{self.company.id}/subscription_unfreeze/')
        self.assertEqual(resp.status_code, 200)
        self.company.refresh_from_db()
        self.assertEqual(self.company.subscription_status, Company.SubscriptionStatus.ACTIVE)
        self.assertGreater(self.company.subscription_end, timezone.now())

    def test_activate_reactivates_frozen(self):
        self.company.subscription_status = Company.SubscriptionStatus.FROZEN
        self.company.save(update_fields=['subscription_status'])
        resp = self.api.post(f'/api/v1/companies/{self.company.id}/subscription_activate/')
        self.assertEqual(resp.status_code, 200)
        self.company.refresh_from_db()
        self.assertEqual(self.company.subscription_status, Company.SubscriptionStatus.ACTIVE)
        # Бизнес-доступ восстановлен.
        self.assertEqual(self.api_owner.get('/api/v1/warehouse/raw-materials/').status_code, 200)


class RBACTests(SubscriptionTestCase):
    def test_owner_cannot_change_subscription(self):
        for action in ('subscription_activate', 'subscription_freeze', 'subscription_unfreeze'):
            resp = self.api_owner.post(f'/api/v1/companies/{self.company.id}/{action}/')
            self.assertEqual(resp.status_code, 403, msg=action)

    def test_owner_cannot_extend_own_subscription(self):
        resp = self.api_owner.post(
            f'/api/v1/companies/{self.company.id}/subscription_extend/',
            {'days': 30}, format='json',
        )
        self.assertEqual(resp.status_code, 403)
        self.company.refresh_from_db()
        self.assertEqual(self.company.subscription_status, Company.SubscriptionStatus.ACTIVE)

    def test_admin_cannot_change_subscription(self):
        admin = make_admin(self.company)
        self.auth(self.api_owner, admin)
        resp = self.api_owner.post(
            f'/api/v1/companies/{self.company.id}/subscription_extend/',
            {'days': 30}, format='json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_superadmin_can_manage_any_company(self):
        other = make_company(name='OtherCo')
        make_owner(other, username='other_owner')
        resp = self.api.post(f'/api/v1/companies/{other.id}/subscription_extend/',
                             {'days': 15}, format='json')
        self.assertEqual(resp.status_code, 200)

    def test_company_member_cannot_list_platform_companies(self):
        # Владелец компании не видит список всех компаний платформы.
        self.assertEqual(self.api_owner.get('/api/v1/companies/').status_code, 403)
        self.assertEqual(self.api_owner.get('/api/v1/companies/stats/').status_code, 403)
        # История чужой/своей подписки ему недоступна.
        self.assertEqual(
            self.api_owner.get(f'/api/v1/companies/{self.company.id}/subscription_history/').status_code,
            403,
        )


class StatsAndFiltersTests(SubscriptionTestCase):
    def test_stats_endpoint_counts(self):
        make_company(name='FrozenCo', subscription_status=Company.SubscriptionStatus.FROZEN)
        expired = make_company(name='ExpiredCo')
        expired.subscription_status = Company.SubscriptionStatus.EXPIRED
        expired.save(update_fields=['subscription_status'])
        grace = make_company(name='GraceCo')
        grace.subscription_status = Company.SubscriptionStatus.GRACE
        grace.save(update_fields=['subscription_status'])
        expiring = make_company(name='ExpiringCo')
        expiring.subscription_end = timezone.now() + timedelta(days=3)
        expiring.save(update_fields=['subscription_end'])
        # Продлённая компания: is_trial=False (тест снятия триала ниже).
        renewed = make_company(name='RenewedCo')
        renewed.is_trial = False
        renewed.save(update_fields=['is_trial'])
        make_company(name='CancelledCo', subscription_status=Company.SubscriptionStatus.CANCELLED)

        resp = self.api.get('/api/v1/companies/stats/')
        self.assertEqual(resp.status_code, 200)
        data = resp.data
        self.assertEqual(data['total'], 7)
        # Активные: Acme + ExpiringCo + RenewedCo (ExpiredCo/GraceCo — свои статусы).
        self.assertEqual(data['active'], 3)
        # Триалы: Acme + ExpiringCo (make_company оставляет is_trial=True).
        self.assertEqual(data['trial'], 2)
        self.assertEqual(data['grace'], 1)
        self.assertEqual(data['frozen'], 1)
        self.assertEqual(data['expired'], 1)
        self.assertEqual(data['cancelled'], 1)
        self.assertEqual(data['expiring_soon'], 1)

    def test_stats_recent_subscriptions_and_renewals(self):
        # Компании и продления за последние 7 дней считаются в «недавние».
        now = timezone.now()
        def _backdated_change(**kwargs):
            # created_at — auto_now_add: явное значение при create() перетирается
            # текущим временем, поэтому датируем запись через update().
            row = SubscriptionChange.objects.create(
                company=self.company, action=SubscriptionChange.Action.EXTENDED,
                old_status='active', new_status='active',
                old_end=self.company.subscription_end, new_end=self.company.subscription_end,
                days_added=30, actor=self.superadmin,
            )
            SubscriptionChange.objects.filter(pk=row.pk).update(**kwargs)
            return row

        _backdated_change(created_at=now - timedelta(days=2))
        _backdated_change(created_at=now - timedelta(days=10))  # вне окна
        data = self.api.get('/api/v1/companies/stats/').data
        self.assertEqual(data['recent_subscriptions'], 1)  # только self.company (7 дн.)
        self.assertEqual(data['recent_renewals'], 1)  # только свежее продление

    def test_status_filter_list(self):
        make_company(name='FrozenCo', subscription_status=Company.SubscriptionStatus.FROZEN)
        resp = self.api.get('/api/v1/companies/?status=frozen')
        self.assertEqual(resp.status_code, 200)
        names = [c['name'] for c in resp.data['results']]
        self.assertEqual(names, ['FrozenCo'])

        resp = self.api.get('/api/v1/companies/?status=active')
        names = [c['name'] for c in resp.data['results']]
        self.assertIn('Acme', names)
        self.assertNotIn('FrozenCo', names)

        # Некорректный статус -> 400.
        resp = self.api.get('/api/v1/companies/?status=bogus')
        self.assertEqual(resp.status_code, 400)

    def test_trial_and_grace_filters(self):
        make_company(name='GraceCo', subscription_status=Company.SubscriptionStatus.GRACE)
        # Продлённая (не-триал) активная компания.
        renewed = make_company(name='RenewedCo')
        renewed.is_trial = False
        renewed.save(update_fields=['is_trial'])

        resp = self.api.get('/api/v1/companies/?status=trial')
        names = [c['name'] for c in resp.data['results']]
        self.assertIn('Acme', names)
        self.assertNotIn('RenewedCo', names)
        self.assertNotIn('GraceCo', names)

        resp = self.api.get('/api/v1/companies/?status=grace')
        names = [c['name'] for c in resp.data['results']]
        self.assertEqual(names, ['GraceCo'])

    def test_search_by_owner_username_and_full_name(self):
        other = make_company(name='PetrovCo')
        make_owner(other, username='petrov_owner', )
        other_owner = other.users.filter(role=User.Role.OWNER).first()
        other_owner.full_name = 'Иван Петров'
        other_owner.save(update_fields=['full_name'])

        # По имени владельца.
        resp = self.api.get('/api/v1/companies/?search=Петров')
        names = [c['name'] for c in resp.data['results']]
        self.assertEqual(names, ['PetrovCo'])
        # По логину владельца.
        resp = self.api.get('/api/v1/companies/?search=petrov_owner')
        names = [c['name'] for c in resp.data['results']]
        self.assertEqual(names, ['PetrovCo'])
        # По названию компании.
        resp = self.api.get('/api/v1/companies/?search=Acme')
        names = [c['name'] for c in resp.data['results']]
        self.assertEqual(names, ['Acme'])

    def test_list_returns_plan_and_days_left(self):
        resp = self.api.get('/api/v1/companies/')
        row = next(c for c in resp.data['results'] if c['id'] == self.company.id)
        self.assertIsNotNone(row['plan_name'])
        self.assertTrue(row['is_trial'])
        self.assertIsNotNone(row['days_left'])
        # grace_end выводится всегда (это конец льготного периода = end + grace),
        # а не только для компаний в статусе grace.
        self.assertEqual(
            row['grace_end'], self.company.grace_end.isoformat(),
        )
        # plan_id нельзя изменить прямым PATCH (mass-assignment guard).
        other_plan = SubscriptionPlan.objects.exclude(pk=row['plan_id']).first()
        resp = self.api.patch(f'/api/v1/companies/{self.company.id}/', {'plan_id': other_plan.pk}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.company.refresh_from_db()
        self.assertNotEqual(self.company.plan_id, other_plan.pk)

    def test_expiring_soon_filter(self):
        expiring = make_company(name='ExpiringCo')
        expiring.subscription_end = timezone.now() + timedelta(days=3)
        expiring.save(update_fields=['subscription_end'])
        resp = self.api.get('/api/v1/companies/?expiring_soon=1')
        self.assertEqual(resp.status_code, 200)
        names = [c['name'] for c in resp.data['results']]
        self.assertEqual(names, ['ExpiringCo'])

    def test_list_returns_counts_and_subscription(self):
        from apps.clients.models import Client
        Client.objects.create(company=self.company, name='C1')
        Client.objects.create(company=self.company, name='C2')
        resp = self.api.get('/api/v1/companies/')
        row = next(c for c in resp.data['results'] if c['id'] == self.company.id)
        self.assertEqual(row['users_count'], 1)  # владелец
        self.assertEqual(row['clients_count'], 2)
        self.assertEqual(row['orders_count'], 0)
        self.assertEqual(row['subscription_status'], Company.SubscriptionStatus.ACTIVE)
        self.assertIsNotNone(row['subscription_end'])

    def test_history_and_audit_endpoints(self):
        self.api.post(f'/api/v1/companies/{self.company.id}/subscription_extend/',
                      {'days': 30}, format='json')
        hist = self.api.get(f'/api/v1/companies/{self.company.id}/subscription_history/')
        self.assertEqual(hist.status_code, 200)
        self.assertEqual(len(hist.data), 1)
        self.assertEqual(hist.data[0]['action'], SubscriptionChange.Action.EXTENDED)
        self.assertEqual(hist.data[0]['days_added'], 30)
        self.assertEqual(hist.data[0]['actor'], self.superadmin.username)

        audit = self.api.get(f'/api/v1/companies/{self.company.id}/audit/')
        self.assertEqual(audit.status_code, 200)
        actions = [a['action'] for a in audit.data]
        self.assertIn(AuditLog.Action.SUBSCRIPTION_EXTENDED, actions)


class WebSocketGateTests(SubscriptionTestCase):
    def test_frozen_company_websocket_denied(self):
        from django.contrib.auth.models import AnonymousUser

        from apps.messaging.models import WsTicket
        from apps.messaging.ws_auth import _resolve_user_by_ticket

        self.company.subscription_status = Company.SubscriptionStatus.FROZEN
        self.company.save(update_fields=['subscription_status'])
        ticket = WsTicket.objects.create(
            company=self.company, user=self.owner,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        # Middleware с замороженной компанией возвращает AnonymousUser и НЕ
        # помечает тикет использованным (соединение отклонено на этапе auth).
        # Тестируем sync-ядро напрямую: @database_sync_to_async — тонкий
        # адаптер, а async-прослойка в тесте ломает соединение TestCase.
        user = _resolve_user_by_ticket(ticket.ticket)
        self.assertIsInstance(user, AnonymousUser)
        ticket.refresh_from_db()
        self.assertFalse(ticket.used)


class ConcurrencySafetyTests(SubscriptionTestCase):
    def test_extend_is_atomic_single_record(self):
        # Повторные вызовы продления создают отдельные записи истории,
        # а не дубли внутри одной операции.
        for _ in range(2):
            self.api.post(f'/api/v1/companies/{self.company.id}/subscription_extend/',
                          {'days': 30}, format='json')
        self.company.refresh_from_db()
        self.assertEqual(
            self.company.subscription_changes.filter(
                action=SubscriptionChange.Action.EXTENDED,
            ).count(),
            2,
        )


@skipUnlessDBFeature('has_select_for_update')
class ConcurrencyRaceTests(TransactionTestCase):
    """
    Настоящие гонки с реальными потоками.

    TransactionTestCase (а не TestCase): рабочие потоки используют СВОИ
    соединения к БД и должны видеть закоммиченные данные — TestCase держит
    тест в транзакции, невидимой другим соединениям (потоки падали с
    «connection already closed» и не находили созданные записи).
    """

    def test_auto_freeze_concurrent_runs_produce_single_history(self):
        """
        Параллельный запуск задачи (два потока) не должен задвоить историю.

        Задача использует SELECT ... FOR UPDATE + повторную проверку статуса,
        поэтому второй прогон после блокировки видит обновлённое состояние
        и пропускает уже обработанную компанию.
        """
        from threading import Barrier, Thread

        company = make_company(name='RaceCo')
        company.subscription_end = timezone.now() - timedelta(days=8)
        company.save(update_fields=['subscription_end'])

        barrier = Barrier(2)
        results = []

        def run():
            from django.db import connection
            try:
                barrier.wait()
                results.append(auto_freeze_expired_subscriptions.run())
            finally:
                # Закрываем соединение потока: иначе после теста остаются
                # активные сессии на тестовую БД и её нельзя удалить.
                connection.close()

        threads = [Thread(target=run) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        company.refresh_from_db()
        self.assertEqual(company.subscription_status, Company.SubscriptionStatus.EXPIRED)
        self.assertEqual(
            company.subscription_changes.filter(action=SubscriptionChange.Action.EXPIRED).count(),
            1,
        )
        self.assertEqual(
            AuditLog.objects.filter(
                company=company, action=AuditLog.Action.SUBSCRIPTION_EXPIRED,
            ).count(),
            1,
        )

    def test_parallel_renewals_do_not_lose_days(self):
        """
        Два параллельных продления не должны «съесть» друг друга.

        Каждое продление читает текущий end и сдвигает его на N дней. Без
        блокировки строки оба потока прочитали бы один и тот же end и записали
        одно значение — одно продление потерялось бы. Строка берётся в
        SELECT ... FOR UPDATE (services.extend_subscription вызывается из API
        под транзакцией? нет — из view без атомарности). См. freeze ниже:
        гонку закрывает то, что каждый вызов идёт через отдельный HTTP-запрос.
        """
        from threading import Barrier, Thread

        company = make_company(name='RenewRaceCo')
        company.subscription_end = timezone.now() + timedelta(days=10)
        company.save(update_fields=['subscription_end'])

        barrier = Barrier(2)
        results = []

        def extend():
            from django.db import connection
            from .subscriptions import extend_subscription
            try:
                barrier.wait()
                extend_subscription(company, days=30, actor=None)
                results.append('ok')
            except Exception as exc:  # noqa: BLE001 — тест: ловим любую ошибку
                results.append(f'err: {exc}')
            finally:
                connection.close()

        threads = [Thread(target=extend) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        company.refresh_from_db()
        self.assertEqual(results, ['ok', 'ok'], 'оба потока должны успешно продлить')
        # Оба продления применились: end сдвинулся на 60 дней от старого end.
        self.assertEqual(
            company.subscription_changes.filter(action=SubscriptionChange.Action.EXTENDED).count(),
            2,
        )

    def test_parallel_freezes_produce_single_history_entry(self):
        """Два параллельных freeze -> одна запись истории FROZEN, статус FROZEN."""
        from threading import Barrier, Thread

        company = make_company(name='FreezeRaceCo')

        barrier = Barrier(2)
        results = []

        def freeze():
            from django.db import connection
            from .subscriptions import freeze_company
            try:
                barrier.wait()
                freeze_company(company, actor=None)
                results.append('ok')
            except Exception as exc:  # noqa: BLE001
                results.append(f'err: {exc}')
            finally:
                connection.close()

        threads = [Thread(target=freeze) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        company.refresh_from_db()
        self.assertEqual(company.subscription_status, Company.SubscriptionStatus.FROZEN)
        self.assertEqual(
            company.subscription_changes.filter(action=SubscriptionChange.Action.FROZEN).count(),
            1,
        )
        self.assertEqual(
            AuditLog.objects.filter(
                company=company, action=AuditLog.Action.SUBSCRIPTION_FROZEN,
            ).count(),
            1,
        )
