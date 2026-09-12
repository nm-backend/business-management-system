"""
Интеграционные тесты защищённой раздачи /media/.

Регрессия: /media/ раньше отдавался через django.views.static.serve без
авторизации — чеки, аватары и аттачменты чужой компании были доступны по
прямой ссылке любому знающему URL. Теперь serve_protected_media проверяет:
аутентификацию (401), подписку компании, владельца файла в БД и ролевые
права, зеркалящие соответствующий API-эндпоинт.

Файл намеренно назван test_media_security.py (discovery-паттерн Django
'test*.py' покрывает и tests_*-файлы, и этот).
"""
import datetime
import shutil
import tempfile
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import re_path, resolve

from apps.accounts.models import User
from apps.clients.models import Client
from apps.companies.models import Company
from apps.core.media_views import _clean_relative_path, serve_protected_media
from apps.finance.models import Expense, LaborRate
from apps.messaging.models import ChatMessage
from apps.messaging.services import (
    ensure_general_conversation,
    get_or_create_direct,
)
from apps.orders.models import Order
from apps.production.models import Task, WorkPhoto, WorkRecord
from apps.warehouse.models import FinishedProduct, RawMaterial

# URLconf только для этих тестов: маршрут /media/ -> защищённое view.
# (В тестовых настройках DEBUG=False и MEDIA_SERVE не задан, поэтому боевой
# urls.py маршрут не монтирует — проверяем view через тот же путь.)
urlpatterns = [
    re_path(r'^media/(?P<path>.*)$', serve_protected_media,
            name='protected-media'),
]


def _upload(name, content=b'fake-image-bytes'):
    return SimpleUploadedFile(name, content, content_type='image/jpeg')


@override_settings(ROOT_URLCONF='apps.core.test_media_security')
class MediaSecurityTests(TestCase):
    """401 анониму, 403 чужой компании, 200 своей (+ ролевые зеркала)."""

    @classmethod
    def setUpClass(cls):
        cls._media_root = tempfile.mkdtemp(prefix='skladpro_test_media_')
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)

    def setUp(self):
        self.company_a = Company.objects.create(name='MediaCo A')
        self.company_b = Company.objects.create(name='MediaCo B')
        self.owner_a = User.objects.create_user(
            username='med_o_a', password='p', role=User.Role.OWNER,
            company=self.company_a,
        )
        self.admin_a = User.objects.create_user(
            username='med_a_a', password='p', role=User.Role.ADMIN,
            company=self.company_a,
        )
        self.worker_a = User.objects.create_user(
            username='med_w_a', password='p', role=User.Role.WORKER,
            company=self.company_a,
        )
        self.worker_a2 = User.objects.create_user(
            username='med_w_a2', password='p', role=User.Role.WORKER,
            company=self.company_a,
        )
        self.owner_b = User.objects.create_user(
            username='med_o_b', password='p', role=User.Role.OWNER,
            company=self.company_b,
        )
        self.superadmin = User.objects.create_user(
            username='med_sa', password='p', role=User.Role.SUPERADMIN,
        )

        # ── Файлы компании A (по одному на каждый upload_to) ──
        self.owner_a.avatar.save('owner_a.jpg', _upload('owner_a.jpg'))
        self.avatar_url = self.owner_a.avatar.url

        self.company_a.logo.save('logo_a.jpg', _upload('logo_a.jpg'))
        self.logo_url = self.company_a.logo.url

        self.material = RawMaterial.objects.create(
            company=self.company_a, name='Мрамор', quantity=Decimal('10'),
            photo=_upload('mat_a.jpg'),
        )
        self.material_url = self.material.photo.url

        self.product = FinishedProduct.objects.create(
            company=self.company_a, name='Столешница', quantity=Decimal('3'),
            photo=_upload('prod_a.jpg'),
        )
        self.product_url = self.product.photo.url

        self.expense = Expense.objects.create(
            company=self.company_a, category='rent', amount=Decimal('5000'),
            date=datetime.date.today(), created_by=self.owner_a,
            receipt_photo=_upload('receipt_a.jpg'),
        )
        self.receipt_url = self.expense.receipt_photo.url

        self.client_a = Client.objects.create(
            company=self.company_a, name='Клиент A',
        )
        self.order = Order.objects.create(
            company=self.company_a, client=self.client_a,
            product=self.product, quantity=Decimal('2'),
            worker=self.worker_a, photo=_upload('order_a.jpg'),
        )
        self.order_url = self.order.photo.url

        self.task = Task.objects.create(
            company=self.company_a, order=self.order, worker=self.worker_a,
            assigned_by=self.owner_a, attachment=_upload('task_a.pdf'),
        )
        self.task_attach_url = self.task.attachment.url

        self.work = WorkRecord.objects.create(
            company=self.company_a, task=self.task, worker=self.worker_a,
            product=self.product, operation=LaborRate.OperationType.CUTTING,
            quantity=Decimal('2'), unit=self.product.unit,
            photo=_upload('work_a.jpg'),
        )
        self.work_photo_url = self.work.photo.url

        self.work_photo_extra = WorkPhoto.objects.create(
            work=self.work, image=_upload('work_extra_a.jpg'),
        )
        self.work_extra_url = self.work_photo_extra.image.url

        general = ensure_general_conversation(self.company_a)
        self.general_msg = ChatMessage.objects.create(
            company=self.company_a, conversation=general,
            sender=self.owner_a, content='',
            attachment=_upload('general_a.pdf'),
            attachment_name='general_a.pdf',
        )
        self.general_attach_url = self.general_msg.attachment.url

        direct, _ = get_or_create_direct(
            self.company_a, self.owner_a, self.admin_a,
        )
        self.direct_msg = ChatMessage.objects.create(
            company=self.company_a, conversation=direct,
            sender=self.owner_a, content='',
            attachment=_upload('direct_a.pdf'),
            attachment_name='direct_a.pdf',
        )
        self.direct_attach_url = self.direct_msg.attachment.url

    # ── Хелперы ──

    def _jwt_for(self, user):
        from rest_framework_simplejwt.tokens import RefreshToken
        return str(RefreshToken.for_user(user).access_token)

    def _get_jwt(self, url, user):
        return self.client.get(
            url, HTTP_AUTHORIZATION=f'Bearer {self._jwt_for(user)}',
        )

    # ── 401: анонимы ──

    def test_anonymous_gets_401_on_material_photo(self):
        response = self.client.get(self.material_url)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['code'], 'authentication_required')

    def test_anonymous_gets_401_on_avatar_and_logo(self):
        for url in (self.avatar_url, self.logo_url, self.direct_attach_url):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 401)

    def test_invalid_jwt_gets_401(self):
        response = self.client.get(
            self.material_url, HTTP_AUTHORIZATION='Bearer invalid.token.here',
        )
        self.assertEqual(response.status_code, 401)

    def test_inactive_user_gets_401(self):
        self.worker_a.is_active = False
        self.worker_a.save(update_fields=['is_active'])
        self.client.force_login(self.worker_a)
        self.assertEqual(self.client.get(self.material_url).status_code, 401)

    # ── 403: чужая компания ──

    def test_cross_company_material_denied(self):
        self.client.force_login(self.owner_b)
        response = self.client.get(self.material_url)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['code'], 'forbidden')

    def test_cross_company_denied_for_all_file_kinds(self):
        self.client.force_login(self.owner_b)
        for url in (
            self.avatar_url, self.logo_url, self.product_url,
            self.receipt_url, self.order_url, self.task_attach_url,
            self.work_photo_url, self.work_extra_url,
            self.general_attach_url, self.direct_attach_url,
        ):
            with self.subTest(url=url):
                self.assertEqual(
                    self.client.get(url).status_code, 403,
                    f'чужой файл доступен: {url}',
                )

    # ── 200: своя компания ──

    def test_owner_reads_own_company_files(self):
        self.client.force_login(self.owner_a)
        for url in (
            self.avatar_url, self.logo_url, self.material_url,
            self.product_url, self.receipt_url, self.order_url,
            self.task_attach_url, self.work_photo_url, self.work_extra_url,
            self.general_attach_url, self.direct_attach_url,
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                content = b''.join(response.streaming_content)
                self.assertEqual(content, b'fake-image-bytes')

    def test_jwt_auth_reads_own_company_file(self):
        response = self._get_jwt(self.material_url, self.worker_a)
        self.assertEqual(response.status_code, 200)

    def test_jwt_cross_company_denied(self):
        response = self._get_jwt(self.material_url, self.owner_b)
        self.assertEqual(response.status_code, 403)

    def test_head_request_allowed(self):
        self.client.force_login(self.owner_a)
        self.assertEqual(self.client.head(self.material_url).status_code, 200)

    def test_post_not_allowed(self):
        self.client.force_login(self.owner_a)
        self.assertEqual(self.client.post(self.material_url).status_code, 405)

    # ── Ролевые зеркала API ──

    def test_receipt_owner_only(self):
        self.client.force_login(self.admin_a)
        self.assertEqual(self.client.get(self.receipt_url).status_code, 403)
        self.client.force_login(self.worker_a)
        self.assertEqual(self.client.get(self.receipt_url).status_code, 403)
        self.client.force_login(self.owner_a)
        self.assertEqual(self.client.get(self.receipt_url).status_code, 200)

    def test_general_chat_attachment_readable_by_any_member(self):
        # worker_a НЕ участник общего чата явно — общий чат читают все.
        self.client.force_login(self.worker_a2)
        self.assertEqual(
            self.client.get(self.general_attach_url).status_code, 200,
        )

    def test_direct_chat_attachment_participants_only(self):
        self.client.force_login(self.worker_a2)  # не участник диалога
        self.assertEqual(
            self.client.get(self.direct_attach_url).status_code, 403,
        )
        self.client.force_login(self.admin_a)  # участник диалога
        self.assertEqual(
            self.client.get(self.direct_attach_url).status_code, 200,
        )

    def test_order_photo_worker_only_own(self):
        self.client.force_login(self.worker_a)  # назначен на заказ
        self.assertEqual(self.client.get(self.order_url).status_code, 200)
        self.client.force_login(self.worker_a2)  # чужой заказ
        self.assertEqual(self.client.get(self.order_url).status_code, 403)

    def test_task_attachment_worker_only_own(self):
        self.client.force_login(self.worker_a)
        self.assertEqual(
            self.client.get(self.task_attach_url).status_code, 200,
        )
        self.client.force_login(self.worker_a2)
        self.assertEqual(
            self.client.get(self.task_attach_url).status_code, 403,
        )

    def test_work_photos_worker_only_own(self):
        self.client.force_login(self.worker_a)
        self.assertEqual(
            self.client.get(self.work_photo_url).status_code, 200,
        )
        self.assertEqual(
            self.client.get(self.work_extra_url).status_code, 200,
        )
        self.client.force_login(self.worker_a2)
        self.assertEqual(
            self.client.get(self.work_photo_url).status_code, 403,
        )
        self.assertEqual(
            self.client.get(self.work_extra_url).status_code, 403,
        )

    def test_stock_photos_readable_by_worker(self):
        self.client.force_login(self.worker_a2)
        self.assertEqual(self.client.get(self.material_url).status_code, 200)
        self.assertEqual(self.client.get(self.product_url).status_code, 200)

    def test_avatar_same_company_readable(self):
        self.client.force_login(self.worker_a2)
        self.assertEqual(self.client.get(self.avatar_url).status_code, 200)

    # ── Суперадмин ──

    def test_superadmin_reads_logo_and_avatar_only(self):
        self.client.force_login(self.superadmin)
        self.assertEqual(self.client.get(self.logo_url).status_code, 200)
        self.assertEqual(self.client.get(self.avatar_url).status_code, 200)
        # Бизнес-контент компаний суперадмину закрыт.
        for url in (
            self.material_url, self.product_url, self.receipt_url,
            self.order_url, self.task_attach_url, self.work_photo_url,
            self.general_attach_url, self.direct_attach_url,
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    # ── Подписка ──

    def test_frozen_company_cannot_read_media(self):
        self.company_a.subscription_status = (
            Company.SubscriptionStatus.FROZEN
        )
        self.company_a.save(update_fields=['subscription_status'])
        self.client.force_login(self.owner_a)
        response = self.client.get(self.material_url)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()['code'], 'subscription_expired',
        )

    # ── 404: нет файла / нет владельца / мусор ──

    def test_missing_file_is_404(self):
        self.material.photo.delete(save=False)
        self.material.refresh_from_db()
        self.client.force_login(self.owner_a)
        self.assertEqual(self.client.get(self.material_url).status_code, 404)

    def test_orphan_file_without_db_owner_is_404(self):
        import os

        orphan = os.path.join(self._media_root, 'avatars', 'orphan_x.jpg')
        os.makedirs(os.path.dirname(orphan), exist_ok=True)
        with open(orphan, 'wb') as f:
            f.write(b'orphan')
        self.client.force_login(self.owner_a)
        self.assertEqual(
            self.client.get('/media/avatars/orphan_x.jpg').status_code, 404,
        )

    def test_unknown_prefix_is_404(self):
        import os

        strange = os.path.join(self._media_root, 'other', 'x.bin')
        os.makedirs(os.path.dirname(strange), exist_ok=True)
        with open(strange, 'wb') as f:
            f.write(b'x')
        self.client.force_login(self.owner_a)
        self.assertEqual(
            self.client.get('/media/other/x.bin').status_code, 404,
        )

    def test_path_traversal_is_404(self):
        self.client.force_login(self.owner_a)
        for url in (
            '/media/../media/materials/x.jpg',
            '/media/avatars/../../etc/passwd',
            '/media/avatars/..%2F..%2Fsecret',
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_clean_relative_path_rejects_garbage(self):
        for bad in ('', '..', '../x', '/abs', 'a\\b', 'a\x00b', '.'):
            with self.subTest(bad=bad):
                from django.http import Http404

                with self.assertRaises(Http404):
                    _clean_relative_path(bad)
        self.assertEqual(
            _clean_relative_path('avatars/a.jpg'), 'avatars/a.jpg',
        )

    # ── X-Accel-Redirect / X-Sendfile ──

    @override_settings(PROTECTED_MEDIA_ACCEL_LOCATION='/protected-media/')
    def test_nginx_accel_redirect_served_after_checks(self):
        self.client.force_login(self.owner_b)
        denied = self.client.get(self.material_url)
        self.assertEqual(denied.status_code, 403)
        self.assertNotIn('X-Accel-Redirect', denied)
        self.client.force_login(self.owner_a)
        response = self.client.get(self.material_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response['X-Accel-Redirect'],
            f'/protected-media/{self.material.photo.name}',
        )
        self.assertEqual(response.content, b'')

    @override_settings(PROTECTED_MEDIA_SENDFILE=True)
    def test_apache_sendfile_served_after_checks(self):
        self.client.force_login(self.owner_b)
        denied = self.client.get(self.material_url)
        self.assertEqual(denied.status_code, 403)
        self.assertNotIn('X-Sendfile', denied)
        self.client.force_login(self.owner_a)
        response = self.client.get(self.material_url)
        self.assertEqual(response.status_code, 200)
        import os

        # Имя на диске может получить случайный суффикс при коллизии
        # (общий временный MEDIA_ROOT на весь класс) — сверяем с фактом.
        self.assertTrue(
            response['X-Sendfile'].endswith(
                os.path.basename(self.material.photo.name),
            ),
        )
        self.assertEqual(response.content, b'')


class MediaUrlconfTests(TestCase):
    """Боевой urls.py монтирует /media/ на защищённое view, а не static()."""

    def _reload_urlconf(self, debug, media_serve):
        import importlib

        from django.conf import settings
        from django.urls import clear_url_caches

        import skladpro.urls as urls_module

        original = urls_module.urlpatterns
        with override_settings(DEBUG=debug, MEDIA_SERVE=media_serve):
            importlib.reload(urls_module)
            # get_resolver() закэширован по объекту модуля, а reload мутирует
            # его in place: без сброса resolve() видел бы старые паттерны.
            clear_url_caches()
            try:
                match = resolve('/media/avatars/a.jpg',
                                urlconf=urls_module)
                patterns = list(urls_module.urlpatterns)
            finally:
                urls_module.urlpatterns = original
                clear_url_caches()
        return match, patterns

    def test_debug_mounts_protected_view(self):
        from django.conf import settings

        match, patterns = self._reload_urlconf(True, False)
        self.assertIs(match.func, serve_protected_media)
        for pattern in patterns:
            callback = getattr(pattern, 'callback', None)
            if getattr(callback, '__module__', '') != 'django.views.static':
                continue
            # static.serve разрешён только для публичной статики (STATIC_URL);
            # MEDIA_ROOT через него раздаваться не должен.
            served_root = str(
                getattr(pattern, 'default_kwargs', {}).get('document_root', ''),
            )
            self.assertNotEqual(
                served_root, str(settings.MEDIA_ROOT),
                'прямая раздача static.serve запрещена для /media/',
            )

    def test_media_serve_mounts_protected_view(self):
        match, _ = self._reload_urlconf(False, True)
        self.assertIs(match.func, serve_protected_media)

    def test_no_media_route_without_debug_or_serve(self):
        from django.urls import Resolver404

        match = None
        import importlib

        from django.urls import clear_url_caches

        import skladpro.urls as urls_module

        original = urls_module.urlpatterns
        with override_settings(DEBUG=False, MEDIA_SERVE=False):
            importlib.reload(urls_module)
            clear_url_caches()
            try:
                try:
                    match = resolve('/media/avatars/a.jpg',
                                    urlconf=urls_module)
                except Resolver404:
                    match = None
            finally:
                urls_module.urlpatterns = original
                clear_url_caches()
        # Либо нет маршрута, либо SPA-fallback — но НЕ static.serve и НЕ медиа-view.
        if match is not None:
            self.assertIsNot(match.func, serve_protected_media)
            self.assertNotEqual(
                getattr(match.func, '__module__', ''),
                'django.views.static',
            )
