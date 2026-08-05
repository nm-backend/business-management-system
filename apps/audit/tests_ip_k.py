"""
Мусорный X-Forwarded-For не должен ронять аудируемые эндпоинты в 500.

XFF вида 'unknown, 1.2.3.4' (nginx не распознал клиента) или произвольный мусор
попадал в AuditLog.ip_address — inet-колонку Postgres — без валидации, и любое
аудируемое действие падало с DataError, а на оплате откатывался весь платёж.
"""
from django.test import TestCase, RequestFactory

from apps.audit.services import get_client_ip


class GetClientIpTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _ip(self, xff=None, remote=None):
        request = self.factory.post('/api/v1/core/health/')
        meta = request.META
        if xff is not None:
            meta['HTTP_X_FORWARDED_FOR'] = xff
        if remote is not None:
            meta['REMOTE_ADDR'] = remote
        return get_client_ip(request)

    def test_clean_xff_returns_first_ip(self):
        self.assertEqual(self._ip(xff='1.2.3.4, 5.6.7.8'), '1.2.3.4')

    def test_junk_xff_returns_none(self):
        # Мусорный XFF не проходит в audit, но валидный REMOTE_ADDR остаётся.
        self.assertEqual(self._ip(xff='unknown, 1.2.3.4'), '127.0.0.1')
        self.assertIsNone(self._ip(xff='not-an-ip', remote='??'))

    def test_junk_xff_falls_back_to_remote_addr(self):
        self.assertEqual(self._ip(xff='garbage', remote='10.0.0.1'), '10.0.0.1')

    def test_junk_remote_addr_returns_none(self):
        self.assertIsNone(self._ip(xff=None, remote='??'))

    def test_none_request_returns_none(self):
        self.assertIsNone(get_client_ip(None))
