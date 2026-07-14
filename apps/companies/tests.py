"""
Тесты изоляции арендаторов (multi-tenant).

Проверяют, что пользователь одной компании НИКОГДА не видит и не может
изменить данные другой компании, а супер-администратор управляет компаниями,
но не имеет доступа к бизнес-данным.
"""
import datetime
from decimal import Decimal

from rest_framework.test import APIClient
from django.test import TestCase

from apps.accounts.models import User
from apps.clients.models import Client
from apps.companies.models import Company
from apps.orders.models import Order
from apps.warehouse.models import FinishedProduct, RawMaterial


def make_company(name):
    company = Company.objects.create(name=name)
    owner = User.objects.create_user(username=f'{name}_owner', password='pw', role=User.Role.OWNER, company=company)
    worker = User.objects.create_user(username=f'{name}_worker', password='pw', role=User.Role.WORKER, company=company)
    material = RawMaterial.objects.create(company=company, name=f'{name}_marble', quantity=Decimal('10'))
    product = FinishedProduct.objects.create(company=company, name=f'{name}_slab', quantity=Decimal('5'))
    client = Client.objects.create(company=company, name=f'{name}_client')
    order = Order.objects.create(
        company=company, client=client, product=product,
        quantity=Decimal('1'), unit='izdelie', deadline=datetime.date(2024, 1, 1),
    )
    return {
        'company': company, 'owner': owner, 'worker': worker,
        'material': material, 'product': product, 'client': client, 'order': order,
    }


class TenantIsolationTests(TestCase):
    def setUp(self):
        self.a = make_company('AlphaCo')
        self.b = make_company('BetaCo')
        self.api = APIClient()

    def auth(self, user):
        self.api.force_authenticate(user=user)

    def test_materials_list_isolated(self):
        self.auth(self.a['owner'])
        resp = self.api.get('/api/v1/warehouse/raw-materials/')
        names = [m['name'] for m in resp.data['results']]
        self.assertIn('AlphaCo_marble', names)
        self.assertNotIn('BetaCo_marble', names)

    def test_cannot_retrieve_other_company_material(self):
        self.auth(self.a['owner'])
        resp = self.api.get(f'/api/v1/warehouse/raw-materials/{self.b["material"].id}/')
        self.assertEqual(resp.status_code, 404)

    def test_clients_list_isolated(self):
        self.auth(self.a['owner'])
        resp = self.api.get('/api/v1/clients/clients/')
        names = [c['name'] for c in resp.data['results']]
        self.assertEqual(names, ['AlphaCo_client'])

    def test_orders_list_isolated(self):
        self.auth(self.a['owner'])
        resp = self.api.get('/api/v1/orders/orders/')
        ids = [o['id'] for o in resp.data['results']]
        self.assertIn(self.a['order'].id, ids)
        self.assertNotIn(self.b['order'].id, ids)

    def test_cannot_create_order_for_other_company_client(self):
        self.auth(self.a['owner'])
        resp = self.api.post('/api/v1/orders/orders/', {
            'client': self.b['client'].id, 'quantity': '1', 'unit': 'izdelie',
        }, format='json')
        self.assertIn(resp.status_code, (403, 400))
        # Заказ для чужого клиента не создан.
        self.assertFalse(Order.objects.filter(client=self.b['client'], company=self.a['company']).exists())

    def test_owner_analytics_scoped_to_company(self):
        self.auth(self.a['owner'])
        resp = self.api.get('/api/v1/reports/analytics/owner/')
        self.assertEqual(resp.status_code, 200)
        # A создала 1 заказ; аналитика не должна считать заказ B.
        self.assertEqual(resp.data['orders_count'], 1)

    def test_employees_scoped_to_company(self):
        self.auth(self.a['worker'])
        resp = self.api.get('/api/v1/messaging/employees/')
        rows = resp.data['results'] if isinstance(resp.data, dict) else resp.data
        usernames = [u['username'] for u in rows]
        self.assertTrue(all('BetaCo' not in u for u in usernames))
        self.assertNotIn(self.a['worker'].username, usernames)  # себя не показываем

    def test_cannot_start_direct_with_other_company_user(self):
        # Владелец A пытается открыть личный диалог с владельцем B.
        self.auth(self.a['owner'])
        resp = self.api.post('/api/v1/messaging/conversations/start_direct/', {
            'user_id': self.b['owner'].id,
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_conversations_isolated_by_company(self):
        from apps.messaging.models import ChatMessage
        from apps.messaging.services import ensure_general_conversation
        # Общий чат и сообщение внутри компании B.
        conv_b = ensure_general_conversation(self.b['company'])
        ChatMessage.objects.create(
            company=self.b['company'], conversation=conv_b,
            sender=self.b['owner'], content='secret B',
        )
        self.auth(self.a['owner'])
        # Список бесед A не содержит беседу компании B.
        resp = self.api.get('/api/v1/messaging/conversations/')
        rows = resp.data['results'] if isinstance(resp.data, dict) else resp.data
        self.assertNotIn(conv_b.id, [c['id'] for c in rows])
        # Прямой доступ к чужой беседе и её сообщениям — 404.
        self.assertEqual(self.api.get(f'/api/v1/messaging/conversations/{conv_b.id}/').status_code, 404)
        self.assertEqual(self.api.get(f'/api/v1/messaging/conversations/{conv_b.id}/messages/').status_code, 404)
        # Отправка в чужую беседу запрещена.
        post = self.api.post('/api/v1/messaging/messages/', {
            'conversation': conv_b.id, 'content': 'inject',
        }, format='json')
        self.assertEqual(post.status_code, 400)
        self.assertFalse(ChatMessage.objects.filter(content='inject').exists())

    def test_worker_cannot_be_assigned_across_companies(self):
        self.auth(self.a['owner'])
        resp = self.api.post('/api/v1/production/tasks/', {
            'order': self.a['order'].id, 'worker': self.b['worker'].id,
        }, format='json')
        self.assertIn(resp.status_code, (403, 400))


class CompanyAdminTests(TestCase):
    """SaaS-онбординг через Django Admin: компания + владелец за один шаг."""

    def setUp(self):
        from django.test import Client
        self.sa = User.objects.create_superuser(username='admin_root', password='pw12345X')
        self.client = Client()
        self.client.force_login(self.sa)

    def test_admin_creates_company_with_owner(self):
        resp = self.client.post('/admin/companies/company/add/', {
            'name': 'AdminMadeCo', 'is_active': 'on',
            'owner_username': 'am_owner', 'owner_password': 'Str0ng!Pass9',
            'owner_full_name': 'AM Owner', 'owner_phone': '',
        })
        self.assertIn(resp.status_code, (200, 302))
        company = Company.objects.get(name='AdminMadeCo')
        owner = User.objects.get(username='am_owner')
        self.assertEqual(owner.company, company)
        self.assertEqual(owner.role, User.Role.OWNER)
        self.assertTrue(owner.check_password('Str0ng!Pass9'))

    def test_admin_add_company_requires_owner(self):
        resp = self.client.post('/admin/companies/company/add/', {
            'name': 'NoOwnerCo', 'is_active': 'on',
            'owner_username': '', 'owner_password': '',
        })
        self.assertEqual(resp.status_code, 200)  # форма с ошибкой валидации
        self.assertFalse(Company.objects.filter(name='NoOwnerCo').exists())


class SuperAdminTests(TestCase):
    def setUp(self):
        self.superadmin = User.objects.create_superuser(username='root', password='pw')
        self.api = APIClient()

    def test_superadmin_creates_company_with_owner(self):
        self.api.force_authenticate(user=self.superadmin)
        resp = self.api.post('/api/v1/companies/', {
            'name': 'GammaCo',
            'owner_username': 'gamma_owner',
            'owner_password': 'Str0ng!Pass',
            'owner_full_name': 'Gamma Owner',
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        company = Company.objects.get(name='GammaCo')
        owner = User.objects.get(username='gamma_owner')
        self.assertEqual(owner.company, company)
        self.assertEqual(owner.role, User.Role.OWNER)

    def test_superadmin_blocked_from_tenant_data(self):
        self.api.force_authenticate(user=self.superadmin)
        # Супер-админ не состоит в компании -> нет доступа к бизнес-данным.
        self.assertEqual(self.api.get('/api/v1/warehouse/raw-materials/').status_code, 403)
        self.assertEqual(self.api.get('/api/v1/clients/clients/').status_code, 403)
        self.assertEqual(self.api.get('/api/v1/orders/orders/').status_code, 403)

    def test_company_member_blocked_from_company_management(self):
        company = Company.objects.create(name='DeltaCo')
        owner = User.objects.create_user(username='d_owner', password='pw', role=User.Role.OWNER, company=company)
        self.api.force_authenticate(user=owner)
        self.assertEqual(self.api.get('/api/v1/companies/').status_code, 403)

    def test_blocked_company_owner_cannot_login(self):
        company = Company.objects.create(name='EpsilonCo', is_active=True)
        User.objects.create_user(username='e_owner', password='secretpw', role=User.Role.OWNER, company=company)
        # Блокируем компанию (как это делает toggle_active) - деактивируем пользователей.
        company.is_active = False
        company.save()
        User.objects.filter(company=company).update(is_active=False)
        resp = self.api.post('/api/v1/accounts/login/', {'username': 'e_owner', 'password': 'secretpw'}, format='json')
        self.assertEqual(resp.status_code, 400)
