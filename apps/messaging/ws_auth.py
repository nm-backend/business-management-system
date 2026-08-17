"""
Тикет-аутентификация для WebSocket (Django Channels).

Access-токен НЕ передаётся в query-строке WebSocket-URL: он попадает в логи
прокси/балансировщика и течёт с них. Клиент получает одноразовый коротко-
живущий тикет (WsTicket) по REST (Authorization-заголовок), а WebSocket
открывает только с ним. Middleware валидирует тикет, помечает его
использованным и кладёт пользователя в scope.
"""
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone


def _resolve_user_by_ticket(ticket):
    """
    Валидирует одноразовый тикет (sync-ядро) и возвращает пользователя
    или AnonymousUser.

    Вынесено в обычную функцию, чтобы логика тестировалась напрямую (без
    async-прослойки); @database_sync_to_async ниже — тонкий адаптер для
    middleware.
    """
    from django.db import transaction

    from apps.accounts.models import User

    from .models import WsTicket

    if not ticket:
        return AnonymousUser()
    try:
        with transaction.atomic():
            ws_ticket = WsTicket.objects.select_for_update().select_related(
                'user', 'user__company',
            ).get(
                ticket=ticket, used=False, expires_at__gt=timezone.now(),
            )
            user = ws_ticket.user
            if not user.is_active or user.blocked_by_owner:
                return AnonymousUser()
            # SaaS gate: замороженной/истёкшей компании чат тоже недоступен —
            # SPA всё равно не откроет соединение, но и прямое подключение
            # в обход UI не должно работать.
            if user.company_id is not None and not user.company.is_subscription_active:
                return AnonymousUser()
            # Одноразовость: помечаем использованным ДО открытия соединения.
            ws_ticket.used = True
            ws_ticket.save(update_fields=['used'])
            return user
    except WsTicket.DoesNotExist:
        return AnonymousUser()


@database_sync_to_async
def _get_user_by_ticket(ticket):
    """Async-обёртка для middleware (см. _resolve_user_by_ticket)."""
    return _resolve_user_by_ticket(ticket)


class TicketAuthMiddleware(BaseMiddleware):
    """Аутентифицирует WebSocket-соединение по одноразовому тикету из query-строки."""

    async def __call__(self, scope, receive, send):
        query = parse_qs(scope.get('query_string', b'').decode())
        ticket = (query.get('ticket') or [None])[0]
        scope['user'] = await _get_user_by_ticket(ticket)
        return await super().__call__(scope, receive, send)
