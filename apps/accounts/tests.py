"""
Unit-тесты для приложения accounts: кастомный UserManager, свойства User,
навыки (Skill), и система Access Key (коды-приглашения сотрудников).
"""
from datetime import timedelta

from django.test import Client, TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.access_keys import issue_access_key, redeem_access_key
from apps.accounts.models import AccessKey, Skill, User
from apps.companies.models import Company


class UserManagerTests(TestCase):
    def test_create_user_sets_password_and_defaults(self):
        user = User.objects.create_user(username='john', password='secret123')
        self.assertEqual(user.username, 'john')
        self.assertTrue(user.check_password('secret123'))
        # Роль по умолчанию — worker.
        self.assertEqual(user.role, User.Role.WORKER)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_create_user_without_username_raises(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(username='', password='x')

    def test_create_user_accepts_extra_fields(self):
        user = User.objects.create_user(
            username='mary', password='p', role=User.Role.ADMIN, full_name='Mary M'
        )
        self.assertEqual(user.role, User.Role.ADMIN)
        self.assertEqual(user.full_name, 'Mary M')

    def test_create_superuser_defaults(self):
        # Django-суперпользователь = платформенный супер-администратор (без компании).
        superadmin = User.objects.create_superuser(username='boss', password='p')
        self.assertTrue(superadmin.is_staff)
        self.assertTrue(superadmin.is_superuser)
        self.assertEqual(superadmin.role, User.Role.SUPERADMIN)
        self.assertIsNone(superadmin.company)
        self.assertTrue(superadmin.is_superadmin)

    def test_create_superuser_respects_overrides(self):
        owner = User.objects.create_superuser(
            username='boss2', password='p', is_staff=False
        )
        self.assertFalse(owner.is_staff)

    def test_role_filters_return_only_active_matching_users(self):
        User.objects.create_user(username='o1', role=User.Role.OWNER)
        admin = User.objects.create_user(username='a1', role=User.Role.ADMIN)
        User.objects.create_user(username='w1', role=User.Role.WORKER)
        inactive_worker = User.objects.create_user(
            username='w2', role=User.Role.WORKER, is_active=False
        )

        self.assertEqual(list(User.objects.owners().values_list('username', flat=True)), ['o1'])
        self.assertEqual(list(User.objects.admins()), [admin])
        workers = User.objects.workers()
        self.assertIn('w1', workers.values_list('username', flat=True))
        self.assertNotIn(inactive_worker, workers)


class UserModelPropertyTests(TestCase):
    def test_role_properties(self):
        owner = User(username='o', role=User.Role.OWNER)
        admin = User(username='a', role=User.Role.ADMIN)
        worker = User(username='w', role=User.Role.WORKER)

        self.assertTrue(owner.is_owner)
        self.assertFalse(owner.is_admin)
        self.assertTrue(admin.is_admin)
        self.assertTrue(worker.is_worker)
        self.assertFalse(worker.is_owner)

    def test_display_role_returns_human_label(self):
        self.assertEqual(User(role=User.Role.OWNER).display_role, 'Egasi')
        self.assertEqual(User(role=User.Role.ADMIN).display_role, 'Administrator')
        self.assertEqual(User(role=User.Role.WORKER).display_role, 'Ishchi')

    def test_str_prefers_full_name(self):
        self.assertEqual(str(User(username='u', full_name='Full Name')), 'Full Name')

    def test_str_falls_back_to_username(self):
        self.assertEqual(str(User(username='u', full_name='')), 'u')


class SetupOwnerAPITests(TestCase):
    def setUp(self):
        self.api = APIClient()

    def test_setup_accepts_empty_phone(self):
        response = self.api.post(
            '/api/v1/accounts/setup/owner/',
            {
                'username': 'owner',
                # Пароль должен проходить CommonPasswordValidator.
                'password': 'Skl4dPro!Nod',
                'password_confirm': 'Skl4dPro!Nod',
                'full_name': 'Owner',
                'phone': '',
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertIn('tokens', response.data)
        self.assertEqual(User.objects.get(username='owner').phone, '')


def _company(name):
    company = Company.objects.create(name=name)
    owner = User.objects.create_user(username=f'{name}_owner', password='pw', role=User.Role.OWNER, company=company)
    admin = User.objects.create_user(username=f'{name}_admin', password='pw', role=User.Role.ADMIN, company=company)
    worker = User.objects.create_user(username=f'{name}_worker', password='pw', role=User.Role.WORKER, company=company)
    return company, owner, admin, worker


class AccessKeyModelTests(TestCase):
    def setUp(self):
        self.company, self.owner, self.admin, self.worker = _company('Alpha')
        # Ключи выпускаются только приглашённым (без рабочего пароля) — см.
        # запрет has_usable_password в issue_access_key.
        self.worker.set_unusable_password()
        self.worker.save()

    def test_code_format(self):
        key = issue_access_key(user=self.worker, created_by=self.owner)
        self.assertTrue(key.key.startswith('SKP-'))
        self.assertEqual(len(key.key.split('-')), 4)

    def test_redeemable_and_expiry(self):
        key = issue_access_key(user=self.worker, created_by=self.owner)
        self.assertTrue(key.is_redeemable)
        self.assertEqual(key.effective_status, 'active')
        key.expires_at = timezone.now() - timedelta(days=1)
        key.save()
        self.assertTrue(key.is_expired)
        self.assertFalse(key.is_redeemable)
        self.assertEqual(key.effective_status, 'expired')

    def test_issue_revokes_previous_active(self):
        first = issue_access_key(user=self.worker, created_by=self.owner)
        second = issue_access_key(user=self.worker, created_by=self.owner)
        first.refresh_from_db()
        self.assertEqual(first.status, AccessKey.Status.REVOKED)
        self.assertEqual(second.status, AccessKey.Status.ACTIVE)

    def test_cannot_issue_for_superadmin(self):
        # Сервис запрещает ключи для супер-админа / пользователя без компании.
        # (Политика «не владельцу» применяется на уровне API.)
        root = User.objects.create_superuser(username='root_sa', password='pw12345X')
        with self.assertRaises(ValueError):
            issue_access_key(user=root, created_by=self.owner)


class AccessKeyServiceTests(TestCase):
    def setUp(self):
        self.company, self.owner, self.admin, self.worker = _company('Beta')
        self.worker.set_unusable_password()
        self.worker.save()

    def test_redeem_activates_and_is_one_time(self):
        self.worker.set_unusable_password()
        self.worker.is_active = False
        self.worker.save()
        key = issue_access_key(user=self.worker, created_by=self.owner)

        user, err = redeem_access_key(code=key.key, new_password='Str0ng!Pass9')
        self.assertIsNone(err)
        self.assertEqual(user.id, self.worker.id)
        self.worker.refresh_from_db()
        self.assertTrue(self.worker.is_active)
        self.assertTrue(self.worker.check_password('Str0ng!Pass9'))
        key.refresh_from_db()
        self.assertEqual(key.status, AccessKey.Status.USED)
        self.assertIsNotNone(key.used_at)

        # Повторно тот же ключ не срабатывает.
        user2, err2 = redeem_access_key(code=key.key, new_password='Another!Pass9')
        self.assertIsNone(user2)
        self.assertEqual(err2, 'invalid')

    def test_redeem_blocked_for_inactive_company(self):
        key = issue_access_key(user=self.worker, created_by=self.owner)
        self.company.is_active = False
        self.company.save()
        user, err = redeem_access_key(code=key.key, new_password='Str0ng!Pass9')
        self.assertIsNone(user)
        self.assertEqual(err, 'company_inactive')

    def test_case_insensitive_code(self):
        key = issue_access_key(user=self.worker, created_by=self.owner)
        user, err = redeem_access_key(code=key.key.lower(), new_password='Str0ng!Pass9')
        self.assertIsNone(err)
        self.assertEqual(user.id, self.worker.id)


class AccessKeyAPITests(TestCase):
    def setUp(self):
        self.company, self.owner, self.admin, self.worker = _company('Gamma')
        self.other_company, self.b_owner, _, self.b_worker = _company('Delta')
        self.api = APIClient()

    def test_owner_issues_key_for_worker(self):
        # Активный сотрудник с паролем не получает ключ (захват аккаунта).
        self.api.force_authenticate(self.owner)
        resp = self.api.post(f'/api/v1/accounts/users/{self.worker.id}/access_key/')
        self.assertEqual(resp.status_code, 400)
        # Приглашённый (без пароля) — получает.
        invited = User.objects.create_user(username='gamma_invited',
                                           role=User.Role.WORKER, company=self.company)
        invited.set_unusable_password()
        invited.save()
        resp = self.api.post(f'/api/v1/accounts/users/{invited.id}/access_key/')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertTrue(resp.data['key'].startswith('SKP-'))
        self.assertEqual(resp.data['status'], 'active')

    def test_cannot_issue_for_owner_account(self):
        self.api.force_authenticate(self.owner)
        resp = self.api.post(f'/api/v1/accounts/users/{self.owner.id}/access_key/')
        self.assertEqual(resp.status_code, 400)

    def test_issue_isolated_by_company(self):
        # Владелец Gamma не может выпустить ключ сотруднику Delta (404 — вне выборки).
        self.api.force_authenticate(self.owner)
        resp = self.api.post(f'/api/v1/accounts/users/{self.b_worker.id}/access_key/')
        self.assertEqual(resp.status_code, 404)

    def test_worker_cannot_issue(self):
        self.api.force_authenticate(self.worker)
        resp = self.api.post(f'/api/v1/accounts/users/{self.worker.id}/access_key/')
        self.assertEqual(resp.status_code, 403)

    def test_verify_and_redeem_flow_then_login(self):
        invited = User.objects.create_user(username='gamma_invited2',
                                           role=User.Role.WORKER, company=self.company)
        invited.set_unusable_password()
        invited.save()
        self.api.force_authenticate(self.owner)
        issued = self.api.post(f'/api/v1/accounts/users/{invited.id}/access_key/').data
        code = issued['key']

        pub = APIClient()
        # verify
        v = pub.post('/api/v1/accounts/access-key/verify/', {'access_key': code}, format='json')
        self.assertTrue(v.data['valid'])
        self.assertEqual(v.data['employee']['company'], 'Gamma')
        # redeem
        r = pub.post('/api/v1/accounts/access-key/redeem/', {'access_key': code, 'new_password': 'Str0ng!Pass9'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertIn('tokens', r.data)
        # employee can now log in with the chosen password
        login = pub.post('/api/v1/accounts/login/', {'username': invited.username, 'password': 'Str0ng!Pass9'}, format='json')
        self.assertEqual(login.status_code, 200)

    def test_verify_invalid_code(self):
        pub = APIClient()
        v = pub.post('/api/v1/accounts/access-key/verify/', {'access_key': 'SKP-XXXX-XXXX-XXXX'}, format='json')
        self.assertFalse(v.data['valid'])

    def test_redeem_invalid_code(self):
        pub = APIClient()
        r = pub.post('/api/v1/accounts/access-key/redeem/', {'access_key': 'SKP-XXXX-XXXX-XXXX', 'new_password': 'Str0ng!Pass9'}, format='json')
        self.assertEqual(r.status_code, 400)


class InviteWithoutPasswordTests(TestCase):
    def setUp(self):
        self.company, self.owner, self.admin, self.worker = _company('Epsilon')
        self.api = APIClient()

    def test_owner_creates_employee_without_password_then_access_key(self):
        self.api.force_authenticate(self.owner)
        # create employee without a password (invited)
        resp = self.api.post('/api/v1/accounts/users/', {
            'username': 'invited1', 'full_name': 'Invited One', 'role': 'worker',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        invited = User.objects.get(username='invited1')
        self.assertFalse(invited.has_usable_password())
        # issue + redeem
        code = self.api.post(f'/api/v1/accounts/users/{invited.id}/access_key/').data['key']
        pub = APIClient()
        r = pub.post('/api/v1/accounts/access-key/redeem/', {'access_key': code, 'new_password': 'Str0ng!Pass9'}, format='json')
        self.assertEqual(r.status_code, 200)
        invited.refresh_from_db()
        self.assertTrue(invited.has_usable_password())


class SkillAPITests(TestCase):
    def setUp(self):
        self.company, self.owner, self.admin, self.worker = _company('Zeta')
        self.other_company, self.b_owner, _, _ = _company('Eta')
        self.api = APIClient()

    def test_skills_endpoint_registered_and_crud(self):
        self.api.force_authenticate(self.owner)
        create = self.api.post('/api/v1/accounts/skills/', {'name': 'Python', 'category': 'Tech'}, format='json')
        self.assertEqual(create.status_code, 201, create.data)
        lst = self.api.get('/api/v1/accounts/skills/')
        rows = lst.data['results'] if isinstance(lst.data, dict) else lst.data
        self.assertIn('Python', [s['name'] for s in rows])

    def test_skills_isolated_by_company(self):
        Skill.objects.create(company=self.other_company, name='SecretSkill')
        self.api.force_authenticate(self.owner)
        lst = self.api.get('/api/v1/accounts/skills/')
        rows = lst.data['results'] if isinstance(lst.data, dict) else lst.data
        self.assertNotIn('SecretSkill', [s['name'] for s in rows])

    def test_worker_cannot_create_skill(self):
        self.api.force_authenticate(self.worker)
        resp = self.api.post('/api/v1/accounts/skills/', {'name': 'X'}, format='json')
        self.assertEqual(resp.status_code, 403)


class ImageUploadValidatorTests(TestCase):
    """Валидация загрузки изображений (размер/тип) — защита от вредоносных загрузок."""

    class _Fake:
        def __init__(self, name, size, content_type='image/png'):
            self.name = name
            self.size = size
            self.content_type = content_type

    def test_rejects_too_large(self):
        from django.core.exceptions import ValidationError
        from apps.core.validators import MAX_IMAGE_SIZE, validate_image_upload
        with self.assertRaises(ValidationError):
            validate_image_upload(self._Fake('a.png', MAX_IMAGE_SIZE + 1))

    def test_rejects_bad_extension(self):
        from django.core.exceptions import ValidationError
        from apps.core.validators import validate_image_upload
        with self.assertRaises(ValidationError):
            validate_image_upload(self._Fake('evil.exe', 1024, 'application/x-msdownload'))

    def test_rejects_bad_content_type(self):
        from django.core.exceptions import ValidationError
        from apps.core.validators import validate_image_upload
        with self.assertRaises(ValidationError):
            validate_image_upload(self._Fake('a.png', 1024, 'application/octet-stream'))

    def test_accepts_valid_image(self):
        from apps.core.validators import validate_image_upload
        # не должно бросать исключение
        validate_image_upload(self._Fake('photo.jpg', 500 * 1024, 'image/jpeg'))


class AdminSmokeTests(TestCase):
    """Проверяет, что кастомные админки открываются без ошибок (500)."""
    def setUp(self):
        self.company, self.owner, self.admin, self.worker = _company('Theta')
        self.worker.set_unusable_password()
        self.worker.save()
        issue_access_key(user=self.worker, created_by=self.owner)
        self.superadmin = User.objects.create_superuser(username='root', password='pw12345X')
        self.client = Client()
        self.client.force_login(self.superadmin)

    def test_changelists_load(self):
        for url in [
            '/admin/accounts/user/',
            '/admin/accounts/skill/',
            '/admin/accounts/accesskey/',
            '/admin/companies/company/',
            '/admin/warehouse/rawmaterial/',
            '/admin/orders/order/',
        ]:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_company_change_page_with_stats(self):
        resp = self.client.get(f'/admin/companies/company/{self.company.id}/change/')
        self.assertEqual(resp.status_code, 200)
