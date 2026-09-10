"""
Экран «Бугунги вазифаларим» (ТЗ): серверный фильтр scope=today.

Раньше вкладка работника показывала ВСЕ его задачи, а «сегодняшних» как
списка не существовало. Фильтр: незавершённые задачи, у которых дедлайн
сегодня, просрочен или не задан вовсе.
"""
from datetime import datetime, time, timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.production.models import Task, TaskStatus

TASKS = '/api/v1/production/tasks/'


def local_deadline_today(hour=18):
    """Сегодняшний дедлайн в ЛОКАЛЬНОЙ зоне (settings.TIME_ZONE).

    timezone.now().replace(hour=18) — это 18:00 UTC, что в Бишкеке уже
    завтра: дата не совпадает с localdate() и фильтр её исключает.
    """
    return timezone.make_aware(datetime.combine(timezone.localdate(), time(hour)))


class TodayScopeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='TodayCo')
        cls.owner = User.objects.create_user(
            username='t_owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )
        cls.worker = User.objects.create_user(
            username='t_worker', password='pw', role=User.Role.WORKER, company=cls.company,
        )

    def api_as(self, user):
        api = APIClient()
        api.force_authenticate(user)
        return api

    def _create(self, title, *, deadline=None, status=TaskStatus.PENDING, days_ago=0):
        now = timezone.now()
        return Task.objects.create(
            company=self.company, worker=self.worker, assigned_by=self.owner,
            status=status, title=title, deadline=deadline,
            created_at=now - timedelta(days=days_ago) if days_ago else None,
        )

    def test_today_includes_due_today_overdue_and_undated(self):
        due_today = self._create('Сегодня', deadline=local_deadline_today())
        overdue = self._create(
            'Просрочен', deadline=timezone.now() - timedelta(days=2),
        )
        undated_old = self._create('Без срока (старая)', days_ago=10)
        due_next_week = self._create('На следующей неделе', deadline=timezone.now() + timedelta(days=7))

        response = self.api_as(self.worker).get(TASKS, {'scope': 'today'})
        self.assertEqual(response.status_code, 200)
        ids = {t['id'] for t in response.data['results']}
        self.assertIn(due_today.id, ids)
        self.assertIn(overdue.id, ids)
        self.assertIn(undated_old.id, ids)
        self.assertNotIn(due_next_week.id, ids)

    def test_today_excludes_finished_statuses(self):
        done = self._create('Подтверждена', status=TaskStatus.CONFIRMED)
        refused = self._create('Отказана', status=TaskStatus.REFUSED)
        response = self.api_as(self.worker).get(TASKS, {'scope': 'today'})
        ids = {t['id'] for t in response.data['results']}
        self.assertNotIn(done.id, ids)
        self.assertNotIn(refused.id, ids)

    def test_without_scope_all_tasks_returned(self):
        """Без scope поведение прежнее: список не режется."""
        self._create('Сегодня', deadline=timezone.now())
        future = self._create('Будущее', deadline=timezone.now() + timedelta(days=5))
        response = self.api_as(self.worker).get(TASKS)
        ids = {t['id'] for t in response.data['results']}
        self.assertEqual(ids, {t.id for t in Task.objects.all()})
        self.assertIn(future.id, ids)

    def test_scope_respects_worker_isolation(self):
        """Чужому работнику «сегодняшние» задачи другого работника не видны."""
        other = User.objects.create_user(
            username='t_worker2', password='pw', role=User.Role.WORKER, company=self.company,
        )
        Task.objects.create(
            company=self.company, worker=other, assigned_by=self.owner,
            status=TaskStatus.PENDING, title='Чужая',
        )
        mine = Task.objects.create(
            company=self.company, worker=self.worker, assigned_by=self.owner,
            status=TaskStatus.PENDING, title='Моя',
        )
        response = self.api_as(self.worker).get(TASKS, {'scope': 'today'})
        ids = {t['id'] for t in response.data['results']}
        self.assertEqual(ids, {mine.id})
