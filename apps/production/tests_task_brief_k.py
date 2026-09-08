"""
Тесты полей постановки задачи (макеты «Вазифа юбориш» / «Вазифа тафсилоти»).

Раньше Task = заказ + работник + статус: что делать, к какому сроку, в каком
цехе и по какому чертежу — нигде не хранилось.
"""
from datetime import timedelta
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.companies.models import Company
from apps.orders.models import Order
from apps.production.models import Task, TaskStatus

TASKS = '/api/v1/production/tasks/'


class TaskBriefFieldsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='Granit')
        cls.owner = User.objects.create_user(
            username='owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )
        cls.worker = User.objects.create_user(
            username='worker', password='pw', role=User.Role.WORKER, company=cls.company,
        )
        client_obj = Client.objects.create(company=cls.company, name='Акбаров')
        cls.order = Order.objects.create(
            company=cls.company, client=client_obj, custom_product_name='Столешница',
            quantity=Decimal('1'), unit='sht', total_amount=Decimal('1000'),
            deadline=timezone.now() + timedelta(days=5),
        )

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def test_task_created_with_brief_fields(self):
        deadline = (timezone.now() + timedelta(days=2)).replace(microsecond=0)
        response = self.api.post(TASKS, {
            'order': self.order.id,
            'worker': self.worker.id,
            'title': 'Столешница 2000x600',
            'description': 'Полировка кромки, фаска 5 мм',
            'deadline': deadline.isoformat(),
            'workshop': 'Цех-1',
            'size': '2000x600',
            'thickness': '20.00',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)

        task = Task.objects.get(pk=response.data['id'])
        self.assertEqual(task.title, 'Столешница 2000x600')
        self.assertEqual(task.workshop, 'Цех-1')
        self.assertEqual(task.size, '2000x600')
        self.assertEqual(task.thickness, Decimal('20.00'))
        self.assertEqual(task.deadline, deadline)

    def test_attachment_uploaded_with_original_name(self):
        drawing = SimpleUploadedFile('Чизма.pdf', b'%PDF-1.4 fake', content_type='application/pdf')
        response = self.api.post(TASKS, {
            'order': self.order.id,
            'worker': self.worker.id,
            'title': 'Столешница',
            'attachment': drawing,
        }, format='multipart')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data['attachment'])
        self.assertEqual(response.data['attachment_name'], 'Чизма.pdf')

    def test_dangerous_attachment_rejected(self):
        bad = SimpleUploadedFile('drawing.html', b'<script>alert(1)</script>', content_type='text/html')
        response = self.api.post(TASKS, {
            'order': self.order.id, 'worker': self.worker.id,
            'title': 'Столешница', 'attachment': bad,
        }, format='multipart')
        self.assertEqual(response.status_code, 400)
        self.assertIn('attachment', response.data)

    def test_deadline_in_past_rejected(self):
        response = self.api.post(TASKS, {
            'order': self.order.id, 'worker': self.worker.id, 'title': 'Столешница',
            'deadline': (timezone.now() - timedelta(days=1)).isoformat(),
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('deadline', response.data)

    def test_assigned_task_without_order_requires_title(self):
        response = self.api.post(TASKS, {'worker': self.worker.id}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('title', response.data)

    def test_worker_self_task_without_title_still_allowed(self):
        """Самостоятельная работа работника не ломается новым требованием."""
        api = APIClient()
        api.force_authenticate(self.worker)
        response = api.post(TASKS, {'worker': self.worker.id}, format='json')
        self.assertEqual(response.status_code, 201, response.data)

    def test_worker_sees_brief_in_list(self):
        self.api.post(TASKS, {
            'order': self.order.id, 'worker': self.worker.id,
            'title': 'Столешница', 'workshop': 'Цех-2',
        }, format='json')
        api = APIClient()
        api.force_authenticate(self.worker)
        response = api.get(TASKS)
        results = response.data['results'] if 'results' in response.data else response.data
        self.assertEqual(results[0]['title'], 'Столешница')
        self.assertEqual(results[0]['workshop'], 'Цех-2')

    def test_is_overdue_uses_task_deadline(self):
        task = Task.objects.create(
            company=self.company, worker=self.worker, assigned_by=self.owner,
            title='Столешница', status=TaskStatus.ACCEPTED,
            deadline=timezone.now() - timedelta(hours=1),
        )
        self.assertTrue(task.is_overdue)

        task.status = TaskStatus.CONFIRMED
        self.assertFalse(task.is_overdue, 'сданная задача не просрочена')

    def test_is_overdue_falls_back_to_order_deadline(self):
        self.order.deadline = timezone.now() - timedelta(days=1)
        self.order.save(update_fields=['deadline'])
        task = Task.objects.create(
            company=self.company, order=self.order, worker=self.worker,
            assigned_by=self.owner, status=TaskStatus.PENDING,
        )
        self.assertTrue(task.is_overdue)

    def test_cross_company_worker_rejected_with_brief(self):
        other = Company.objects.create(name='Other')
        stranger = User.objects.create_user(
            username='stranger', password='pw', role=User.Role.WORKER, company=other,
        )
        response = self.api.post(TASKS, {
            'worker': stranger.id, 'title': 'Столешница',
        }, format='json')
        self.assertEqual(response.status_code, 403)
