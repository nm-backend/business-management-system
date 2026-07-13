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

    def test_message_recipients_scoped_to_company(self):
        self.auth(self.a['worker'])
        resp = self.api.get('/api/v1/messaging/messages/recipients/')
        usernames = [u['username'] for u in resp.data]
        self.assertTrue(all('BetaCo' not in u for u in usernames))

    def test_cannot_message_user_of_another_company(self):
        # Владелец A пытается написать владельцу B напрямую (подделав recipient).
        self.auth(self.a['owner'])
        resp = self.api.post('/api/v1/messaging/messages/', {
            'recipient': self.b['owner'].id, 'content': 'hi',
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        from apps.messaging.models import Message
        self.assertFalse(Message.objects.filter(recipient=self.b['owner']).exists())

    def test_messages_list_isolated_by_company(self):
        from apps.messaging.models import Message
        # Сообщение внутри компании B.
        Message.objects.create(company=self.b['company'], sender=self.b['owner'],
                               recipient=self.b['worker'], content='secret B')
        self.auth(self.a['owner'])
        resp = self.api.get('/api/v1/messaging/messages/')
        rows = resp.data['results'] if isinstance(resp.data, dict) else resp.data
        contents = [m['content'] for m in rows]
        self.assertNotIn('secret B', contents)

    def test_worker_cannot_be_assigned_across_companies(self):
        self.auth(self.a['owner'])
        resp = self.api.post('/api/v1/production/tasks/', {
            'order': self.a['order'].id, 'worker': self.b['worker'].id,
        }, format='json')
        self.assertIn(resp.status_code, (403, 400))


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
