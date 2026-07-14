"""
JWT-аутентификация для WebSocket (Django Channels).

Браузер не может передать заголовок Authorization при открытии WebSocket,
поэтому access-токен передаётся в query-строке: ws://host/ws/chat/?token=<JWT>.
Middleware валидирует токен через SimpleJWT и кладёт пользователя в scope.
"""
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser


@database_sync_to_async
def _get_user(token):
    """Валидирует access-токен и возвращает пользователя или AnonymousUser."""
    from rest_framework_simplejwt.exceptions import TokenError
    from rest_framework_simplejwt.tokens import AccessToken

    from apps.accounts.models import User

    try:
        access = AccessToken(token)
        user = User.objects.get(pk=access['user_id'], is_active=True)
    except (TokenError, KeyError, User.DoesNotExist, Exception):
        return AnonymousUser()
    return user


class JWTAuthMiddleware(BaseMiddleware):
    """Аутентифицирует WebSocket-соединение по access-токену из query-строки."""

    async def __call__(self, scope, receive, send):
        query = parse_qs(scope.get('query_string', b'').decode())
        token = (query.get('token') or [None])[0]
        scope['user'] = await _get_user(token) if token else AnonymousUser()
        return await super().__call__(scope, receive, send)
