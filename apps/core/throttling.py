"""
Throttling helpers.

Django 5.1 не имеет встроенной обработки X-Forwarded-For для REMOTE_ADDR
(настройки USE_X_FORWARDED_FOR/TRUSTED_PROXIES из Django 4.1 удалены):
за reverse-proxy все анонимные клиенты выглядели одним IP гейта, и scoped-лимиты
(login, access_key_verify/redeem, two_factor) били всех разом или никого.

client_ip_from_xff() доверяет XFF только когда реальный источник соединения
(REMOTE_ADDR) принадлежит приватной сети прокси и ищет первый не-приватный адрес
в цепочке — стандартный trusted-proxy алгоритм.
"""
import ipaddress

from rest_framework.throttling import ScopedRateThrottle

# Приватные сети: nginx на том же хосте, внутренние сети PaaS (Railway/Render),
# docker-сети. Публичные XFF-заголовки, присланные напрямую с не-приватного
# REMOTE_ADDR, игнорируются — их не должен принять ни один публичный узел.
TRUSTED_PROXY_NETS = [
    '127.0.0.1',
    '::1',
    '10.0.0.0/8',
    '172.16.0.0/12',
    '192.168.0.0/16',
]

_TRUSTED = tuple(ipaddress.ip_network(net) for net in TRUSTED_PROXY_NETS)


def _is_trusted(address):
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in net for net in _TRUSTED)


def client_ip_from_xff(meta):
    """Реальный IP клиента с учётом доверенных прокси (или REMOTE_ADDR)."""
    remote = meta.get('REMOTE_ADDR', '')
    if not _is_trusted(remote):
        return remote
    chain = [part.strip() for part in meta.get('HTTP_X_FORWARDED_FOR', '').split(',') if part.strip()]
    for address in reversed(chain):
        if not _is_trusted(address):
            return address
    return remote


class ScopedIPThrottle(ScopedRateThrottle):
    """ScopedRateThrottle, определяющий клиента по IP за reverse-proxy."""

    def get_ident(self, request=None):
        # DRF вызывает get_ident(request); при прямых вызовах (тесты) request
        # берём из self (allow_request уже сохранил его в self.request).
        request = request or getattr(self, 'request', None)
        return client_ip_from_xff(request.META if request else {})
