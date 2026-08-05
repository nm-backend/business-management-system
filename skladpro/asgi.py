"""
ASGI-конфигурация SkladPro.

HTTP обслуживается стандартным Django-приложением, а WebSocket —
через Django Channels: TicketAuthMiddleware аутентифицирует по одноразовому
тикету (access-токен в query-строку не передаётся — он оседал бы в логах
прокси), URLRouter направляет на консьюмеры чата.
"""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'skladpro.settings')

# Django-приложение инициализируем до импорта кода, который трогает модели.
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

from apps.messaging.routing import websocket_urlpatterns  # noqa: E402
from apps.messaging.ws_auth import TicketAuthMiddleware  # noqa: E402

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': AllowedHostsOriginValidator(
        TicketAuthMiddleware(URLRouter(websocket_urlpatterns))
    ),
})
