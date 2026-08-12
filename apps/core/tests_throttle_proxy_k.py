"""
Аудит K: scoped-лимиты (login, access_key, two_factor) обязаны считать клиента
по IP за reverse-proxy.

Django 5.1 не разворачивает X-Forwarded-For для REMOTE_ADDR (USE_X_FORWARDED_FOR
удалён из 4.1): за гейтом все анонимные клиенты выглядели одним IP, лимиты
срабатывали для всех сразу или не работали вовсе.
"""
from unittest.mock import Mock

from django.test import TestCase

from apps.core.throttling import ScopedIPThrottle, client_ip_from_xff


class ClientIpFromXffTests(TestCase):
    def test_direct_connection_uses_remote_addr(self):
        self.assertEqual(
            client_ip_from_xff({'REMOTE_ADDR': '203.0.113.7'}), '203.0.113.7')

    def test_public_remote_addr_ignores_xff(self):
        # Клиент сам шлёт XFF — с публичного адреса заголовку не верим.
        self.assertEqual(
            client_ip_from_xff({
                'REMOTE_ADDR': '203.0.113.7',
                'HTTP_X_FORWARDED_FOR': '1.2.3.4',
            }), '203.0.113.7')

    def test_trusted_gateway_uses_first_public_xff(self):
        # Render/Railway: соединение от приватного гейта, клиент — первый публичный.
        self.assertEqual(
            client_ip_from_xff({
                'REMOTE_ADDR': '10.244.1.5',
                'HTTP_X_FORWARDED_FOR': '203.0.113.7, 10.244.0.1',
            }), '203.0.113.7')

    def test_trusted_gateway_with_full_private_chain_falls_back(self):
        self.assertEqual(
            client_ip_from_xff({
                'REMOTE_ADDR': '172.17.0.2',
                'HTTP_X_FORWARDED_FOR': '10.0.0.9, 172.17.0.1',
            }), '172.17.0.2')

    def test_no_header_falls_back_to_gateway(self):
        self.assertEqual(
            client_ip_from_xff({'REMOTE_ADDR': '127.0.0.1'}), '127.0.0.1')


class ScopedIPThrottleTests(TestCase):
    def _throttle_with_meta(self, meta):
        throttle = ScopedIPThrottle()
        throttle.request = Mock(META=meta)
        throttle.rate = '10/min'
        return throttle

    def test_ident_uses_xff_through_gateway(self):
        throttle = self._throttle_with_meta({
            'REMOTE_ADDR': '10.244.1.5',
            'HTTP_X_FORWARDED_FOR': '203.0.113.7',
        })
        self.assertEqual(throttle.get_ident(), '203.0.113.7')

    def test_ident_uses_remote_addr_without_trusted_proxy(self):
        throttle = self._throttle_with_meta({'REMOTE_ADDR': '203.0.113.8'})
        self.assertEqual(throttle.get_ident(), '203.0.113.8')
