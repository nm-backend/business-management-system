"""
Регрессионные тесты N+1 (ЭТАП 6).

Замер до/после (3 и 12 объектов):
  /accounts/users/         39 -> 3   (константа)
  /messaging/conversations/47 -> 8   (константа)
  /accounts/skills/         5 -> 2   (константа)
  /clients/clients/        26 -> 15  (частично, см. отчёт)
  /orders/orders/          14 -> 15  (не исправлено, см. отчёт)

Тесты фиксируют, что число запросов НЕ растёт с количеством данных.
"""
import datetime
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.access_keys import issue_access_key
from apps.accounts.models import Skill, User
from apps.companies.models import Company


class QueryCountTests(TestCase):
    """Число запросов должно быть одинаковым при 3 и 12 объектах."""

    def _seed(self, n):
        from apps.messaging.models import ChatMessage
        from apps.messaging.services import ensure_general_conversation, get_or_create_direct

        company = Company.objects.create(name=f'Perf{n}')
        owner = User.objects.create_user(username=f'perf_o{n}', password='p',
                                         role=User.Role.OWNER, company=company)
        skills = [Skill.objects.create(company=company, name=f'S{n}_{i}') for i in range(3)]
        workers = []
        for i in range(n):
            w = User.objects.create_user(username=f'perf_w{n}_{i}', password='p',
                                         role=User.Role.WORKER, company=company)
            w.skills.set(skills)
            issue_access_key(user=w, created_by=owner)
            workers.append(w)

        gen = ensure_general_conversation(company)
        ChatMessage.objects.create(company=company, conversation=gen, sender=owner, content='hi')
        for w in workers:
            conv, _ = get_or_create_direct(company, owner, w)
            ChatMessage.objects.create(company=company, conversation=conv, sender=w, content='m')
        return owner

    def _count(self, url, n):
        owner = self._seed(n)
        api = APIClient()
        api.force_authenticate(user=owner)
        with CaptureQueriesContext(connection) as ctx:
            resp = api.get(url)
        self.assertEqual(resp.status_code, 200, url)
        return len(ctx)

    def assert_constant(self, url):
        few = self._count(url, 3)
        many = self._count(url, 12)
        self.assertEqual(
            few, many,
            f'N+1 в {url}: {few} запросов при 3 объектах и {many} при 12',
        )

    def test_users_list_has_no_n_plus_one(self):
        """Было 39 запросов при 12 сотрудниках (COUNT на каждый навык)."""
        self.assert_constant('/api/v1/accounts/users/')

    def test_conversations_list_has_no_n_plus_one(self):
        """Было 47 запросов (last_message + unread_count на каждую беседу)."""
        self.assert_constant('/api/v1/messaging/conversations/')

    def test_skills_list_has_no_n_plus_one(self):
        """employee_count берётся из аннотации, а не COUNT на каждый навык."""
        self.assert_constant('/api/v1/accounts/skills/')

    def test_users_list_query_budget(self):
        """Жёсткий бюджет: список сотрудников укладывается в 5 запросов."""
        owner = self._seed(12)
        api = APIClient()
        api.force_authenticate(user=owner)
        with self.assertNumQueries(3):
            api.get('/api/v1/accounts/users/')

    def test_conversations_query_budget(self):
        """Жёсткий бюджет: список бесед укладывается в 10 запросов."""
        owner = self._seed(12)
        api = APIClient()
        api.force_authenticate(user=owner)
        with CaptureQueriesContext(connection) as ctx:
            api.get('/api/v1/messaging/conversations/')
        self.assertLessEqual(len(ctx), 10, f'бюджет превышен: {len(ctx)}')


class ConversationPayloadTests(TestCase):
    """Оптимизация не должна изменить формат ответа."""

    def setUp(self):
        from apps.messaging.models import ChatMessage
        from apps.messaging.services import ensure_general_conversation

        self.company = Company.objects.create(name='PayloadCo')
        self.owner = User.objects.create_user(username='pl_o', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.worker = User.objects.create_user(username='pl_w', password='p',
                                               role=User.Role.WORKER, company=self.company)
        conv = ensure_general_conversation(self.company)
        ChatMessage.objects.create(company=self.company, conversation=conv,
                                   sender=self.worker, content='последнее сообщение')
        self.api = APIClient()
        self.api.force_authenticate(user=self.owner)

    def _general(self):
        resp = self.api.get('/api/v1/messaging/conversations/')
        rows = resp.data['results'] if isinstance(resp.data, dict) else resp.data
        return next(c for c in rows if c['kind'] == 'general')

    def test_last_message_still_correct(self):
        """last_message берётся из подзапроса — значения те же, что и раньше."""
        general = self._general()
        self.assertEqual(general['last_message']['content'], 'последнее сообщение')
        self.assertEqual(general['last_message']['sender'], self.worker.pk)

    def test_unread_counts_message_from_other_user(self):
        from apps.messaging.models import ChatMessage
        from apps.messaging.services import ensure_general_conversation
        self._general()  # первый вход: указатель прочтения ставится на «сейчас»
        conv = ensure_general_conversation(self.company)
        ChatMessage.objects.create(company=self.company, conversation=conv,
                                   sender=self.worker, content='новое от коллеги')
        self.assertEqual(self._general()['unread_count'], 1)

    def test_own_message_is_not_counted_as_unread(self):
        from apps.messaging.models import ChatMessage
        from apps.messaging.services import ensure_general_conversation
        self._general()
        conv = ensure_general_conversation(self.company)
        ChatMessage.objects.create(company=self.company, conversation=conv,
                                   sender=self.owner, content='моё')
        self.assertEqual(self._general()['unread_count'], 0)
