"""
API tests for production app.

Coverage:
- Task CRUD
- Accept / refuse task actions
- WorkRecord CRUD
- Confirm / reject work actions
- RBAC: owner sees labor_cost, admin/worker don't
- Production pipeline trigger
"""
from decimal import Decimal
from datetime import date
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.warehouse.models import FinishedProduct, RawMaterial, Recipe, RecipeItem
from apps.orders.models import Order, OrderStatus
from apps.production.models import Task, TaskStatus, WorkRecord


def _create_test_data():
    """Creates users, orders, products, materials for tests."""
    owner = User.objects.create_user(
        username='owner', password='owner123', role=User.Role.OWNER
    )
    admin = User.objects.create_user(
        username='admin', password='admin123', role=User.Role.ADMIN
    )
    worker = User.objects.create_user(
        username='worker', password='worker123', role=User.Role.WORKER
    )
    client = Client.objects.create(name='Client')
    product = FinishedProduct.objects.create(
        name='Marble Slab', unit='m2', quantity=0,
        cost_price=Decimal('300'), sale_price=Decimal('800')
    )
    material = RawMaterial.objects.create(
        name='Raw Marble', unit='m2', quantity=100,
        purchase_price=Decimal('200'),
    )
    material2 = RawMaterial.objects.create(
        name='Polish Compound', unit='kg', quantity=50,
        purchase_price=Decimal('50'),
    )
    recipe = Recipe.objects.create(product=product, name='Standard Recipe')
    RecipeItem.objects.create(recipe=recipe, material=material, quantity_required=2, unit='m2')
    RecipeItem.objects.create(recipe=recipe, material=material2, quantity_required=0.5, unit='kg')

    order = Order.objects.create(
        client=client, product=product, quantity=3, unit='m2',
        deadline=date(2026, 12, 31),
    )
    return owner, admin, worker, product, material, material2, order


class TaskCRUDTests(TestCase):
    """Tests for Task CRUD and lifecycle."""

    def setUp(self):
        self.api = APIClient()
        self.owner, self.admin, self.worker, self.product, self.mat1, self.mat2, self.order = \
            _create_test_data()

    def test_owner_can_create_task(self):
        self.api.force_authenticate(user=self.owner)
        response = self.api.post('/api/v1/production/tasks/', {
            'order': self.order.id,
            'worker': self.worker.id,
            'assigned_by': self.owner.id,
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Task.objects.count(), 1)
        self.assertEqual(response.data['status'], TaskStatus.PENDING)

    def test_admin_can_create_task(self):
        self.api.force_authenticate(user=self.admin)
        response = self.api.post('/api/v1/production/tasks/', {
            'order': self.order.id,
            'worker': self.worker.id,
            'assigned_by': self.admin.id,
        })
        self.assertEqual(response.status_code, 201)

    def test_worker_can_see_own_tasks(self):
        self.api.force_authenticate(user=self.worker)
        Task.objects.create(worker=self.worker, assigned_by=self.owner, order=self.order)
        Task.objects.create(worker=self.owner, assigned_by=self.owner, order=self.order)
        response = self.api.get('/api/v1/production/tasks/')
        self.assertEqual(response.status_code, 200)
        data = response.json() if hasattr(response, 'content') else response.data
        results = data.get('results', data) if isinstance(data, dict) else data
        self.assertEqual(len(results), 1)

    def test_owner_sees_all_tasks(self):
        self.api.force_authenticate(user=self.owner)
        Task.objects.create(worker=self.worker, assigned_by=self.owner)
        Task.objects.create(worker=self.admin, assigned_by=self.owner)
        response = self.api.get('/api/v1/production/tasks/')
        self.assertEqual(response.status_code, 200)
        data = response.json() if hasattr(response, 'content') else response.data
        results = data.get('results', data) if isinstance(data, dict) else data
        self.assertEqual(len(results), 2)

    def test_worker_can_accept_task(self):
        self.api.force_authenticate(user=self.worker)
        task = Task.objects.create(worker=self.worker, assigned_by=self.owner)
        response = self.api.post(f'/api/v1/production/tasks/{task.id}/accept/')
        self.assertEqual(response.status_code, 200)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.ACCEPTED)
        self.assertIsNotNone(task.accepted_at)

    def test_worker_cannot_accept_others_task(self):
        self.api.force_authenticate(user=self.worker)
        task = Task.objects.create(worker=self.admin, assigned_by=self.owner)
        response = self.api.post(f'/api/v1/production/tasks/{task.id}/accept/')
        # 404 because worker's queryset doesn't include others' tasks
        self.assertEqual(response.status_code, 404)

    def test_worker_can_refuse_task(self):
        self.api.force_authenticate(user=self.worker)
        task = Task.objects.create(worker=self.worker, assigned_by=self.owner)
        response = self.api.post(f'/api/v1/production/tasks/{task.id}/refuse/', {
            'reason': 'material_insufficient',
            'comment': 'Not enough material'
        })
        self.assertEqual(response.status_code, 200)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.REFUSED)
        self.assertEqual(task.refusal_reason, 'material_insufficient')
        self.assertEqual(task.refusal_comment, 'Not enough material')

    def test_worker_cannot_refuse_others_task(self):
        self.api.force_authenticate(user=self.worker)
        task = Task.objects.create(worker=self.admin, assigned_by=self.owner)
        response = self.api.post(f'/api/v1/production/tasks/{task.id}/refuse/', {
            'reason': 'no_time'
        })
        # 404 because worker's queryset doesn't include others' tasks
        self.assertEqual(response.status_code, 404)

    def test_refuse_requires_reason(self):
        self.api.force_authenticate(user=self.worker)
        task = Task.objects.create(worker=self.worker, assigned_by=self.owner)
        response = self.api.post(f'/api/v1/production/tasks/{task.id}/refuse/', {})
        self.assertEqual(response.status_code, 400)


class WorkRecordTests(TestCase):
    """Tests for WorkRecord CRUD and confirm/reject flow."""

    def setUp(self):
        self.api = APIClient()
        self.owner, self.admin, self.worker, self.product, self.mat1, self.mat2, self.order = \
            _create_test_data()
        self.task = Task.objects.create(
            worker=self.worker, assigned_by=self.owner, order=self.order
        )

    def test_worker_can_create_work_record(self):
        self.api.force_authenticate(user=self.worker)
        response = self.api.post('/api/v1/production/works/', {
            'task': self.task.id,
            'worker': self.worker.id,
            'product': self.product.id,
            'quantity': 2,
            'unit': 'm2',
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(WorkRecord.objects.count(), 1)
        self.assertEqual(response.data['status'], 'awaiting_confirmation')

    def test_owner_sees_labor_cost(self):
        self.api.force_authenticate(user=self.owner)
        wr = WorkRecord.objects.create(
            task=self.task, worker=self.worker, product=self.product,
            quantity=2, unit='m2', labor_cost=Decimal('500'),
        )
        response = self.api.get(f'/api/v1/production/works/{wr.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('labor_cost', response.data)

    def test_admin_does_not_see_labor_cost(self):
        self.api.force_authenticate(user=self.admin)
        wr = WorkRecord.objects.create(
            task=self.task, worker=self.worker, product=self.product,
            quantity=2, unit='m2', labor_cost=Decimal('500'),
        )
        response = self.api.get(f'/api/v1/production/works/{wr.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('labor_cost', response.data)

    def test_worker_does_not_see_labor_cost(self):
        self.api.force_authenticate(user=self.worker)
        wr = WorkRecord.objects.create(
            task=self.task, worker=self.worker, product=self.product,
            quantity=2, unit='m2', labor_cost=Decimal('500'),
        )
        response = self.api.get(f'/api/v1/production/works/{wr.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('labor_cost', response.data)

    def test_worker_sees_only_own_works(self):
        self.api.force_authenticate(user=self.worker)
        WorkRecord.objects.create(
            task=self.task, worker=self.worker, product=self.product,
            quantity=2, unit='m2',
        )
        other_worker = User.objects.create_user(
            username='other', password='other123', role=User.Role.WORKER
        )
        WorkRecord.objects.create(
            task=self.task, worker=other_worker, product=self.product,
            quantity=3, unit='m2',
        )
        response = self.api.get('/api/v1/production/works/')
        self.assertEqual(response.status_code, 200)
        data = response.json() if hasattr(response, 'content') else response.data
        results = data.get('results', data) if isinstance(data, dict) else data
        self.assertEqual(len(results), 1)

    def test_owner_can_confirm_work(self):
        self.api.force_authenticate(user=self.owner)
        wr = WorkRecord.objects.create(
            task=self.task, worker=self.worker, product=self.product,
            quantity=2, unit='m2',
        )
        response = self.api.post(f'/api/v1/production/works/{wr.id}/confirm/', {
            'labor_cost': 1000,
        })
        self.assertEqual(response.status_code, 200)
        wr.refresh_from_db()
        self.assertEqual(wr.status, 'confirmed')
        self.assertIsNotNone(wr.confirmed_at)
        self.assertEqual(wr.labor_cost, 1000)

    def test_admin_can_confirm_work(self):
        self.api.force_authenticate(user=self.admin)
        wr = WorkRecord.objects.create(
            task=self.task, worker=self.worker, product=self.product,
            quantity=2, unit='m2',
        )
        response = self.api.post(f'/api/v1/production/works/{wr.id}/confirm/', {})
        self.assertEqual(response.status_code, 200)
        wr.refresh_from_db()
        self.assertEqual(wr.status, 'confirmed')

    def test_worker_cannot_confirm_work(self):
        self.api.force_authenticate(user=self.worker)
        wr = WorkRecord.objects.create(
            task=self.task, worker=self.worker, product=self.product,
            quantity=2, unit='m2',
        )
        response = self.api.post(f'/api/v1/production/works/{wr.id}/confirm/', {})
        self.assertEqual(response.status_code, 403)

    def test_owner_can_reject_work(self):
        self.api.force_authenticate(user=self.owner)
        wr = WorkRecord.objects.create(
            task=self.task, worker=self.worker, product=self.product,
            quantity=2, unit='m2',
        )
        response = self.api.post(f'/api/v1/production/works/{wr.id}/reject/', {
            'reason': 'Poor quality'
        })
        self.assertEqual(response.status_code, 200)
        wr.refresh_from_db()
        self.assertEqual(wr.status, 'rejected')
        self.assertEqual(wr.rejection_reason, 'Poor quality')

    def test_admin_can_reject_work(self):
        self.api.force_authenticate(user=self.admin)
        wr = WorkRecord.objects.create(
            task=self.task, worker=self.worker, product=self.product,
            quantity=2, unit='m2',
        )
        response = self.api.post(f'/api/v1/production/works/{wr.id}/reject/', {
            'reason': 'Wrong dimensions'
        })
        self.assertEqual(response.status_code, 200)

    def test_worker_cannot_reject_work(self):
        self.api.force_authenticate(user=self.worker)
        wr = WorkRecord.objects.create(
            task=self.task, worker=self.worker, product=self.product,
            quantity=2, unit='m2',
        )
        response = self.api.post(f'/api/v1/production/works/{wr.id}/reject/', {})
        self.assertEqual(response.status_code, 403)

    def test_confirm_updates_order_status(self):
        self.api.force_authenticate(user=self.owner)
        # Set order to a status that pipeline transitions from
        self.order.status = OrderStatus.IN_PROGRESS
        self.order.save()
        wr = WorkRecord.objects.create(
            task=self.task, worker=self.worker, product=self.product,
            quantity=2, unit='m2',
        )
        self.api.post(f'/api/v1/production/works/{wr.id}/confirm/', {
            'labor_cost': 1000,
        })
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'ready')

    def test_confirm_production_pipeline(self):
        """Confirming work should trigger pipeline:
        - Consume raw materials
        - Add finished product
        """
        self.api.force_authenticate(user=self.owner)
        wr = WorkRecord.objects.create(
            task=self.task, worker=self.worker, product=self.product,
            quantity=2, unit='m2',
        )
        self.api.post(f'/api/v1/production/works/{wr.id}/confirm/', {
            'labor_cost': 1000,
        })
        self.mat1.refresh_from_db()
        self.product.refresh_from_db()
        # Material should be consumed
        self.assertLess(self.mat1.quantity, 100)
        # Product quantity should increase
        self.assertGreater(self.product.quantity, 0)

    def test_unauthenticated_cannot_create(self):
        response = self.api.post('/api/v1/production/works/', {
            'quantity': 2, 'unit': 'm2',
        })
        self.assertEqual(response.status_code, 401)
