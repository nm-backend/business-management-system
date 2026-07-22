"""
Финальный адверсариал — доказательство отсутствия IDOR при отправке сообщений.

Проверяем, что ChatMessageViewSet.create отклоняет:
  1. запись в беседу ЧУЖОЙ компании (кросс-тенант);
  2. запись в личный диалог, участником которого отправитель не является.
Это НЕ фикс (код уже защищён validate_conversation) — тесты фиксируют свойство,
чтобы будущие изменения его не сломали.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.messaging.models import Conversation, ConversationParticipant


class ChatMessageIdorTests(TestCase):
    def setUp(self):
        self.a = Company.objects.create(name='A')
        self.b = Company.objects.create(name='B')
        self.a_owner = User.objects.create_user(username='ci_ao', password='p',
                                                 role=User.Role.OWNER, company=self.a)
        self.a_worker = User.objects.create_user(username='ci_aw', password='p',
                                                  role=User.Role.WORKER, company=self.a)
        self.a_worker2 = User.objects.create_user(username='ci_aw2', password='p',
                                                   role=User.Role.WORKER, company=self.a)
        self.b_owner = User.objects.create_user(username='ci_bo', password='p',
                                                 role=User.Role.OWNER, company=self.b)
        # Беседа компании B
        self.conv_b = Conversation.objects.create(company=self.b, kind=Conversation.Kind.GENERAL)
        # Личный диалог между a_owner и a_worker (a_worker2 НЕ участник)
        self.dm = Conversation.objects.create(company=self.a, kind=Conversation.Kind.DIRECT)
        ConversationParticipant.objects.create(conversation=self.dm, user=self.a_owner)
        ConversationParticipant.objects.create(conversation=self.dm, user=self.a_worker)

    def api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def test_cannot_post_to_other_company_conversation(self):
        resp = self.api(self.a_owner).post('/api/v1/messaging/messages/', {
            'conversation': self.conv_b.id, 'content': 'inject'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_cannot_post_to_dm_you_are_not_in(self):
        resp = self.api(self.a_worker2).post('/api/v1/messaging/messages/', {
            'conversation': self.dm.id, 'content': 'eavesdrop'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_participant_can_post_to_own_dm(self):
        resp = self.api(self.a_worker).post('/api/v1/messaging/messages/', {
            'conversation': self.dm.id, 'content': 'привет'}, format='json')
        self.assertEqual(resp.status_code, 201)
