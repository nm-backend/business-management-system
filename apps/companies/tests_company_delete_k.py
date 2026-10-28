"""
Полное удаление компании: API, права, подтверждение, каскад и побочные эффекты.

Тесты намеренно проверяют не только HTTP-код, но и инварианты:
  * данные других компаний не задеты;
  * после CASCADE не осталось строк, включая RESTRICT-связи;
  * медиа удаляются только после коммита, при откате — остаются;
  * платформенный аудит переживает компанию и не содержит бизнес-данных;
  * refresh-токены и WebSocket-сессии не остаются висеть.

Гонки и блокировки проверяются только на PostgreSQL (sqlite не даёт
select_for_update); такие тесты пропускаются локально и идут в CI на PG16.
"""
import datetime
import json
import shutil
import tempfile
import threading
from decimal import Decimal
from pathlib import Path
from unittest import skipUnless
from unittest.mock import AsyncMock, patch

from django.contrib.admin.sites import AdminSite
from django.core.files.uploadedfile import SimpleUploadedFile
from django.conf import settings
from django.db import connection, connections
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import (
    AccessKey, PushSubscription, Skill, User, UserSession,
)
from apps.audit.models import AuditLog
from apps.backup.models import BackupConfig, BackupLog
from apps.clients.models import Client, Payment
from apps.companies.admin import CompanyAdmin
from apps.companies.models import Company, SubscriptionChange, SubscriptionPlan
from apps.companies.tests_subscriptions import make_company, make_owner
from apps.finance.models import Expense, LaborRate, WorkerPayment
from apps.messaging.models import ChatMessage, Conversation, Notification, WsTicket
from apps.orders.models import Order
from apps.production.models import Task, WorkPhoto, WorkRecord
from apps.warehouse.models import (
    FinishedProduct, GoodsReceipt, GoodsReceiptLine, RawMaterial, Recipe,
    RecipeItem, StockMovement, Warehouse, WarehouseCell,
)

IS_POSTGRES = connection.vendor == 'postgresql'
PG_ONLY = 'Требуется PostgreSQL: sqlite не проверяет select_for_update'


def _upload(name):
    return SimpleUploadedFile(name, b'fake-file-bytes', content_type='image/jpeg')


def _paid_plan():
    return SubscriptionPlan.objects.create(
        name='Paid test', code='paid-test', price=Decimal('100.00'),
    )


def _api(user=None):
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


class CompanyDeleteAPITests(TestCase):
    def setUp(self):
        self.superadmin = User.objects.create_superuser(username='root', password='pw')
        self.company = make_company(name='Acme')
        self.owner = make_owner(self.company)
        self.admin = User.objects.create_user(
            username='acme_admin', password='pw', role=User.Role.ADMIN,
            company=self.company,
        )
        self.worker = User.objects.create_user(
            username='acme_worker', password='pw', role=User.Role.WORKER,
            company=self.company,
        )
        self.api = _api(self.superadmin)
        self.url = f'/api/v1/companies/{self.company.pk}/delete/'

    def test_superadmin_deletes_company_with_confirmation(self):
        response = self.api.post(self.url, {'confirm_name': 'Acme'}, format='json')
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Company.objects.filter(pk=self.company.pk).exists())

    def test_delete_endpoint_requires_post(self):
        response = self.api.delete(f'/api/v1/companies/{self.company.pk}/')
        self.assertEqual(response.status_code, 405)
        self.assertTrue(Company.objects.filter(pk=self.company.pk).exists())

    def test_other_roles_forbidden(self):
        for user in (self.owner, self.admin, self.worker):
            response = _api(user).post(self.url, {'confirm_name': 'Acme'}, format='json')
            self.assertEqual(response.status_code, 403, user.role)
            self.assertTrue(Company.objects.filter(pk=self.company.pk).exists())

    def test_anonymous_forbidden(self):
        response = _api().post(self.url, {'confirm_name': 'Acme'}, format='json')
        self.assertIn(response.status_code, (401, 403))
        self.assertTrue(Company.objects.filter(pk=self.company.pk).exists())

    def test_cannot_delete_own_company(self):
        self.superadmin.company = self.company
        self.superadmin.save(update_fields=['company'])
        response = self.api.post(self.url, {'confirm_name': 'Acme'}, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['code'], 'delete_own_company')
        self.assertTrue(Company.objects.filter(pk=self.company.pk).exists())

    def test_confirmation_is_checked_on_server(self):
        for value in ('', '   ', 'acme', 'Acme 2'):
            response = self.api.post(self.url, {'confirm_name': value}, format='json')
            self.assertEqual(response.status_code, 400, value)
            self.assertEqual(response.data['code'], 'delete_name_mismatch')
            self.assertTrue(Company.objects.filter(pk=self.company.pk).exists())

    def test_confirmation_ignores_outer_and_repeated_spaces(self):
        response = self.api.post(
            self.url, {'confirm_name': '  Acme   '}, format='json',
        )
        self.assertEqual(response.status_code, 204)

    def test_confirmation_normalizes_unicode(self):
        company = make_company(name='Cafe\u0301')
        url = f'/api/v1/companies/{company.pk}/delete/'
        response = self.api.post(url, {'confirm_name': 'Caf\u00e9'}, format='json')
        self.assertEqual(response.status_code, 204)

    def test_system_company_cannot_be_deleted(self):
        company = make_company(name='SkladPro', is_system=True)
        url = f'/api/v1/companies/{company.pk}/delete/'
        response = self.api.post(url, {'confirm_name': 'SkladPro'}, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'delete_system_company')
        self.assertTrue(Company.objects.filter(pk=company.pk).exists())

    def test_active_paid_subscription_blocks_delete(self):
        company = make_company(name='PaidCo')
        company.plan = _paid_plan()
        company.is_trial = False
        company.subscription_status = Company.SubscriptionStatus.ACTIVE
        company.subscription_end = timezone.now() + datetime.timedelta(days=10)
        company.save(update_fields=['plan', 'is_trial', 'subscription_status', 'subscription_end'])
        url = f'/api/v1/companies/{company.pk}/delete/'
        response = self.api.post(url, {'confirm_name': 'PaidCo'}, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'delete_paid_subscription')
        self.assertTrue(Company.objects.filter(pk=company.pk).exists())

    def test_grace_paid_subscription_blocks_delete(self):
        company = make_company(name='GraceCo')
        company.plan = _paid_plan()
        company.is_trial = False
        company.subscription_status = Company.SubscriptionStatus.ACTIVE
        company.subscription_end = timezone.now() - datetime.timedelta(days=1)
        company.grace_period_days = 7
        company.save(update_fields=[
            'plan', 'is_trial', 'subscription_status', 'subscription_end',
            'grace_period_days',
        ])
        url = f'/api/v1/companies/{company.pk}/delete/'
        response = self.api.post(url, {'confirm_name': 'GraceCo'}, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'delete_paid_subscription')

    def test_trial_with_paid_plan_can_be_deleted(self):
        company = make_company(name='TrialCo')
        company.plan = _paid_plan()
        company.is_trial = True
        company.save(update_fields=['plan', 'is_trial'])
        url = f'/api/v1/companies/{company.pk}/delete/'
        response = self.api.post(url, {'confirm_name': 'TrialCo'}, format='json')
        self.assertEqual(response.status_code, 204)

    def test_extension_history_does_not_block_delete(self):
        company = make_company(name='ExtendedCo')
        company.plan = _paid_plan()
        company.is_trial = True
        company.save(update_fields=['plan', 'is_trial'])
        SubscriptionChange.objects.create(
            company=company, action=SubscriptionChange.Action.EXTENDED,
            old_status='active', new_status='active',
        )
        url = f'/api/v1/companies/{company.pk}/delete/'
        response = self.api.post(url, {'confirm_name': 'ExtendedCo'}, format='json')
        self.assertEqual(response.status_code, 204)

    def test_free_plan_does_not_block_delete(self):
        company = make_company(name='FreeCo')
        company.is_trial = False
        company.subscription_status = Company.SubscriptionStatus.ACTIVE
        company.subscription_end = timezone.now() + datetime.timedelta(days=10)
        company.save(update_fields=['is_trial', 'subscription_status', 'subscription_end'])
        url = f'/api/v1/companies/{company.pk}/delete/'
        response = self.api.post(url, {'confirm_name': 'FreeCo'}, format='json')
        self.assertEqual(response.status_code, 204)


class CompanyDeleteCascadeTests(TestCase):
    """Один объект на каждую значимую модель + изоляция второго тенанта."""

    def setUp(self):
        self.superadmin = User.objects.create_superuser(username='root', password='pw')
        self.company = make_company(name='CascadeCo')
        self.owner = make_owner(self.company, username='cascade_owner')
        self.worker = User.objects.create_user(
            username='cascade_worker', password='pw',
            role=User.Role.WORKER, company=self.company,
        )
        self.other = make_company(name='OtherCo')
        self.other_owner = make_owner(self.other, username='other_owner')
        self.objects = self._populate(self.company, self.owner, self.worker, 'a')
        self.other_objects = self._populate(
            self.other, self.other_owner,
            User.objects.create_user(
                username='other_worker', password='pw',
                role=User.Role.WORKER, company=self.other,
            ),
            'b',
        )
        # Refresh-токен и метаданные сессии должны исчезнуть вместе с компанией.
        RefreshToken.for_user(self.owner)
        UserSession.objects.create(user=self.owner, jti='cascade-jti')

    def _populate(self, company, owner, worker, suffix):
        client = Client.objects.create(company=company, name=f'Client {suffix}')
        payment = Payment.objects.create(
            company=company, client=client, amount=Decimal('10.00'),
            payment_date=timezone.now(),
        )
        order = Order.objects.create(
            company=company, client=client, quantity=Decimal('1'), unit='sht',
            deadline=timezone.now() + datetime.timedelta(days=3),
        )
        material = RawMaterial.objects.create(
            company=company, name=f'Material {suffix}', quantity=Decimal('10'),
            unit='m2',
        )
        product = FinishedProduct.objects.create(
            company=company, name=f'Product {suffix}', quantity=Decimal('1'),
            unit='sht',
        )
        movement = StockMovement.objects.create(
            company=company, movement_type=StockMovement.MovementType.INCOMING,
            material=material, quantity=Decimal('1'),
        )
        receipt = GoodsReceipt.objects.create(
            company=company, supplier='Supplier', document_number=f'D-{suffix}',
        )
        receipt_line = GoodsReceiptLine.objects.create(
            receipt=receipt, material=material, quantity=Decimal('1'),
        )
        recipe = Recipe.objects.create(
            company=company, product=product, name=f'Recipe {suffix}',
        )
        recipe_item = RecipeItem.objects.create(
            recipe=recipe, material=material, quantity_required=Decimal('1'),
            unit='m2',
        )
        expense = Expense.objects.create(
            company=company, category='rent', amount=Decimal('10'),
            date=datetime.date.today(), created_by=owner,
        )
        rate = LaborRate.objects.create(
            company=company, product=product,
            operation=LaborRate.OperationType.POLISHING,
            rate_per_unit=Decimal('5'), unit='sht',
        )
        worker_payment = WorkerPayment.objects.create(
            company=company, worker=worker, amount=Decimal('10'),
            payment_date=datetime.date.today(),
        )
        task = Task.objects.create(
            company=company, order=order, worker=worker,
            planned_quantity=Decimal('1'), planned_unit='sht',
        )
        work = WorkRecord.objects.create(
            company=company, task=task, worker=worker,
            quantity=Decimal('1'), unit='sht',
        )
        conversation = Conversation.objects.create(
            company=company, kind=Conversation.Kind.GENERAL, created_by=owner,
        )
        message = ChatMessage.objects.create(
            company=company, conversation=conversation, sender=owner,
            content='hello',
        )
        notification = Notification.objects.create(
            company=company, user=owner,
            type=Notification.NotificationType.SUBSCRIPTION_EXPIRING,
            title='t', message='m',
        )
        ticket = WsTicket.objects.create(
            company=company, user=owner, ticket=f'ticket-{suffix}',
            expires_at=timezone.now() + datetime.timedelta(minutes=1),
        )
        push = PushSubscription.objects.create(
            company=company, user=owner, endpoint=f'https://push.example/{suffix}',
            p256dh_key='k', auth_key='a',
        )
        access_key = AccessKey.objects.create(company=company, user=worker)
        skill = Skill.objects.create(company=company, name=f'Skill {suffix}')
        worker.skills.add(skill)
        backup_config = BackupConfig.objects.create(company=company)
        backup_log = BackupLog.objects.create(company=company)
        audit = AuditLog.objects.create(
            company=company, action=AuditLog.Action.CREATE,
            object_type='test', object_id='1',
        )
        warehouse = Warehouse.objects.create(company=company, name=f'Warehouse {suffix}')
        cell = WarehouseCell.objects.create(
            company=company, warehouse=warehouse, code='A-1',
        )
        return {
            'client': client, 'payment': payment, 'order': order,
            'material': material, 'product': product, 'movement': movement,
            'receipt': receipt, 'receipt_line': receipt_line,
            'recipe': recipe, 'recipe_item': recipe_item,
            'expense': expense, 'rate': rate, 'worker_payment': worker_payment,
            'task': task, 'work': work, 'conversation': conversation,
            'message': message, 'notification': notification, 'ticket': ticket,
            'push': push, 'access_key': access_key, 'skill': skill,
            'backup_config': backup_config, 'backup_log': backup_log,
            'audit': audit, 'warehouse': warehouse, 'cell': cell,
        }

    def test_cascade_removes_all_rows_and_keeps_other_tenant(self):
        response = _api(self.superadmin).post(
            f'/api/v1/companies/{self.company.pk}/delete/',
            {'confirm_name': 'CascadeCo'}, format='json',
        )
        self.assertEqual(response.status_code, 204)

        for name, obj in self.objects.items():
            self.assertFalse(
                type(obj).objects.filter(pk=obj.pk).exists(),
                f'осталась строка {name}',
            )
        self.assertFalse(Company.objects.filter(pk=self.company.pk).exists())
        self.assertFalse(OutstandingToken.objects.filter(user_id=self.owner.pk).exists())
        self.assertFalse(UserSession.objects.filter(user_id=self.owner.pk).exists())

        # Второй тенант не задет ни одной из таблиц.
        self.assertTrue(Company.objects.filter(pk=self.other.pk).exists())
        for name, obj in self.other_objects.items():
            self.assertTrue(
                type(obj).objects.filter(pk=obj.pk).exists(),
                f'задет чужой объект {name}',
            )


class CompanyDeleteMediaTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls._media_root = tempfile.mkdtemp(prefix='skladpro_delete_media_')
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)

    def setUp(self):
        self.superadmin = User.objects.create_superuser(username='root', password='pw')
        self.company = make_company(name='MediaCo')
        self.owner = make_owner(self.company, username='media_owner')
        self.worker = User.objects.create_user(
            username='media_worker', password='pw',
            role=User.Role.WORKER, company=self.company,
        )
        self.other = make_company(name='OtherMediaCo')
        self.other.logo.save('other-logo.jpg', _upload('other-logo.jpg'))
        self.other_logo = Path(self.other.logo.path)

        self.paths = []
        self.company.logo.save('logo.jpg', _upload('logo.jpg'))
        self.paths.append(Path(self.company.logo.path))
        self.owner.avatar.save('avatar.jpg', _upload('avatar.jpg'))
        self.paths.append(Path(self.owner.avatar.path))

        material = RawMaterial.objects.create(
            company=self.company, name='Материал', quantity=Decimal('1'),
            photo=_upload('material.jpg'),
        )
        self.paths.append(Path(material.photo.path))
        product = FinishedProduct.objects.create(
            company=self.company, name='Товар', quantity=Decimal('1'),
            photo=_upload('product.jpg'),
        )
        self.paths.append(Path(product.photo.path))
        client = Client.objects.create(company=self.company, name='Клиент')
        order = Order.objects.create(
            company=self.company, client=client, quantity=Decimal('1'),
            unit='sht', deadline=timezone.now() + datetime.timedelta(days=1),
            photo=_upload('order.jpg'),
        )
        self.paths.append(Path(order.photo.path))
        expense = Expense.objects.create(
            company=self.company, category='rent', amount=Decimal('10'),
            date=datetime.date.today(), receipt_photo=_upload('receipt.jpg'),
        )
        self.paths.append(Path(expense.receipt_photo.path))
        task = Task.objects.create(
            company=self.company, worker=self.worker,
            planned_quantity=Decimal('1'), planned_unit='sht',
            attachment=_upload('task.jpg'),
            refusal_attachment=_upload('refusal.jpg'),
        )
        self.paths.extend([Path(task.attachment.path), Path(task.refusal_attachment.path)])
        work = WorkRecord.objects.create(
            company=self.company, task=task, worker=self.worker,
            quantity=Decimal('1'), unit='sht', photo=_upload('work.jpg'),
        )
        self.paths.append(Path(work.photo.path))
        work_photo = WorkPhoto.objects.create(work=work, image=_upload('work-2.jpg'))
        self.paths.append(Path(work_photo.image.path))
        conversation = Conversation.objects.create(
            company=self.company, kind=Conversation.Kind.GENERAL,
        )
        message = ChatMessage.objects.create(
            company=self.company, conversation=conversation, sender=self.owner,
            content='', attachment=_upload('chat.jpg'),
        )
        self.paths.append(Path(message.attachment.path))

    def _delete(self):
        return _api(self.superadmin).post(
            f'/api/v1/companies/{self.company.pk}/delete/',
            {'confirm_name': 'MediaCo'}, format='json',
        )

    def test_media_deleted_after_commit_only(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self._delete()
        self.assertEqual(response.status_code, 204)
        for path in self.paths:
            self.assertFalse(path.exists(), f'файл не удалён: {path}')
        self.assertTrue(self.other_logo.exists(), 'удалён файл чужой компании')

    def test_media_survives_transaction_rollback(self):
        with patch('apps.companies.deletion.write_audit_log', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                self._delete()
        self.assertTrue(Company.objects.filter(pk=self.company.pk).exists())
        for path in self.paths:
            self.assertTrue(path.exists(), f'файл удалён при откате: {path}')
        self.assertTrue(self.other_logo.exists())


class CompanyDeleteAuditAndSocketsTests(TestCase):
    def setUp(self):
        self.superadmin = User.objects.create_superuser(username='root', password='pw')
        self.company = make_company(name='AuditCo')
        self.owner = make_owner(self.company, username='audit_owner')
        self.url = f'/api/v1/companies/{self.company.pk}/delete/'

    def test_platform_audit_survives_company_and_hides_business_data(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = _api(self.superadmin).post(
                self.url, {'confirm_name': 'AuditCo'}, format='json',
            )
        self.assertEqual(response.status_code, 204)
        log = AuditLog.objects.get(
            action=AuditLog.Action.DELETE,
            object_type='companies.company',
        )
        self.assertIsNone(log.company_id)
        self.assertEqual(log.actor_id, self.superadmin.pk)
        self.assertEqual(log.object_repr, 'AuditCo')
        self.assertEqual(log.changes, {})
        self.assertEqual(log.metadata['company_id'], self.company.pk)
        self.assertEqual(log.metadata['company_name'], 'AuditCo')
        self.assertNotIn('orders', log.metadata)
        self.assertNotIn('finance', log.metadata)

    def test_platform_audit_visible_to_superadmin_not_owner(self):
        with self.captureOnCommitCallbacks(execute=True):
            _api(self.superadmin).post(
                self.url, {'confirm_name': 'AuditCo'}, format='json',
            )
        response = _api(self.superadmin).get('/api/v1/audit/logs/platform/')
        self.assertEqual(response.status_code, 200)
        rows = response.data.get('results', response.data)
        self.assertEqual(rows[0]['object_repr'], 'AuditCo')

        response = _api(self.owner).get('/api/v1/audit/logs/platform/')
        self.assertEqual(response.status_code, 403)

    @patch('channels.layers.get_channel_layer')
    def test_websocket_connections_closed_after_commit(self, get_layer):
        layer = AsyncMock()
        get_layer.return_value = layer
        with self.captureOnCommitCallbacks(execute=True):
            response = _api(self.superadmin).post(
                self.url, {'confirm_name': 'AuditCo'}, format='json',
            )
        self.assertEqual(response.status_code, 204)
        layer.group_send.assert_awaited_with(
            f'chat_user_{self.owner.pk}', {'type': 'force_disconnect'},
        )

    @patch('channels.layers.get_channel_layer')
    def test_websocket_not_touched_on_rollback(self, get_layer):
        layer = AsyncMock()
        get_layer.return_value = layer
        with patch('apps.companies.deletion.write_audit_log', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                _api(self.superadmin).post(
                    self.url, {'confirm_name': 'AuditCo'}, format='json',
                )
        layer.group_send.assert_not_awaited()

    def test_admin_delete_is_closed(self):
        request = RequestFactory().get('/admin/')
        request.user = self.superadmin
        admin_view = CompanyAdmin(Company, AdminSite())
        self.assertFalse(admin_view.has_delete_permission(request, self.company))

    def test_i18n_keys_present_in_all_locales(self):
        keys = (
            'delete_title', 'delete_warning', 'delete_input_label',
            'delete_input_placeholder', 'delete_input_hint', 'delete_system_hint',
        )
        error_keys = (
            'delete_name_mismatch', 'delete_own_company',
            'delete_paid_subscription', 'delete_system_company',
            'delete_requires_post', 'not_found',
        )
        for lang in ('uz_cyrl', 'ru', 'ky'):
            path = Path(settings.BASE_DIR) / 'locale' / f'{lang}.json'
            with path.open(encoding='utf-8') as source:
                data = json.load(source)
            for key in keys:
                self.assertIn(key, data['companies'], f'{lang}: companies.{key}')
            for key in error_keys:
                self.assertIn(key, data['errors']['companies'], f'{lang}: errors.companies.{key}')


@skipUnless(IS_POSTGRES, PG_ONLY)
class CompanyDeletePostgresTests(TransactionTestCase):
    """Счастливый путь и двойной клик на PostgreSQL (локально — skip)."""

    def setUp(self):
        self.superadmin = User.objects.create_superuser(username='root', password='pw')
        self.company = make_company(name='PgCo')
        self.owner = make_owner(self.company, username='pg_owner')
        self.url = f'/api/v1/companies/{self.company.pk}/delete/'

    def _post(self):
        return _api(self.superadmin).post(
            self.url, {'confirm_name': 'PgCo'}, format='json',
        )

    def test_delete_success_with_plan(self):
        self.company.plan = SubscriptionPlan.get_default_plan()
        self.company.save(update_fields=['plan'])
        response = self._post()
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Company.objects.filter(pk=self.company.pk).exists())

    def test_delete_success_without_plan(self):
        self.company.plan = None
        self.company.save(update_fields=['plan'])
        response = self._post()
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Company.objects.filter(pk=self.company.pk).exists())

    def test_delete_with_restrict_relations(self):
        """RESTRICT (приход и рецепт) не мешает удалению внутри одного каскада."""
        material = RawMaterial.objects.create(
            company=self.company, name='Гранит', quantity=Decimal('10'), unit='m2',
        )
        product = FinishedProduct.objects.create(
            company=self.company, name='Столешница', quantity=Decimal('1'), unit='sht',
        )
        receipt = GoodsReceipt.objects.create(
            company=self.company, supplier='Поставщик', document_number='PG-1',
        )
        GoodsReceiptLine.objects.create(
            receipt=receipt, material=material, quantity=Decimal('1'),
        )
        recipe = Recipe.objects.create(
            company=self.company, product=product, name='Рецепт',
        )
        RecipeItem.objects.create(
            recipe=recipe, material=material, quantity_required=Decimal('1'),
            unit='m2',
        )
        response = self._post()
        self.assertEqual(response.status_code, 204)
        self.assertFalse(GoodsReceiptLine.objects.filter(receipt_id=receipt.pk).exists())
        self.assertFalse(RecipeItem.objects.filter(recipe_id=recipe.pk).exists())

    def test_two_parallel_deletes(self):
        barrier = threading.Barrier(2)
        results = []
        lock = threading.Lock()

        def worker():
            try:
                barrier.wait(timeout=30)
                response = self._post()
                outcome = response.status_code
            except Exception as exc:  # noqa: BLE001
                outcome = exc
            finally:
                connections.close_all()
            with lock:
                results.append(outcome)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        self.assertEqual(sorted(results), [204, 404])
        self.assertFalse(Company.objects.filter(pk=self.company.pk).exists())
