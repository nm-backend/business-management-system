"""
Единый subscription gate для бизнес-функций.

Один middleware перехватывает ВСЕ запросы к /api/v1/* от пользователей
компаний (owner/admin/manager/worker), чья подписка заморожена или истекла,
и отвечает 403 с code='subscription_expired'. Новые эндпоинты попадают под
гейт автоматически — не нужно помнить про permission на каждом view.

WHITELIST (доступно в frozen state):
  - вход и выход                /accounts/login/, /logout/, /token/refresh/
  - профиль и безопасность      /accounts/me/ (+ password, language, 2fa)
  - статус подписки и оплата    /billing/
  - активация по Access Key     /accounts/access-key/
  - push-подписки               /accounts/push/
  - служебные                   /core/, /schema/, /swagger/, /redoc/

Заморозка НЕ трогает Company.is_active и is_active пользователей — логин
работает (в отличие от блокировки компании toggle_active), но любой
бизнес-запрос получает понятную ошибку.

Почему middleware, а не DRF-permission:
у многих view заданы собственные permission_classes, и добавление permission
в DEFAULT_PERMISSION_CLASSES молча терялось бы на них. Middleware — одна
точка, покрывающая всё, включая будущие эндпоинты.
"""
from django.http import JsonResponse

from .models import Subscription

GATE_API_PREFIX = '/api/v1/'

WHITELIST_PREFIXES = (
    # вход / выход / refresh
    '/api/v1/accounts/login/',
    '/api/v1/accounts/logout/',
    '/api/v1/accounts/token/refresh/',
    # профиль: данные, пароль, язык, 2FA
    '/api/v1/accounts/me/',
    # активация по Access Key и push-подписки (не бизнес-данные)
    '/api/v1/accounts/access-key/',
    '/api/v1/accounts/push/',
    # подписка: статус, продление, счета — оплата должна работать при заморозке
    '/api/v1/billing/',
    # служебные: health, локали, справчники валют, swagger
    '/api/v1/core/',
    '/api/v1/schema/',
    '/api/v1/swagger/',
    '/api/v1/redoc/',
)

SUBSCRIPTION_EXPIRED_CODE = 'subscription_expired'


def _should_enforce(path):
    if not path.startswith(GATE_API_PREFIX):
        return False
    return not path.startswith(WHITELIST_PREFIXES)


class SubscriptionGateMiddleware:
    """403 {'code': 'subscription_expired'} для бизнес-запросов замороженных компаний."""

    def __init__(self, get_response):
        self.get_response = get_response
        # Единственная точка аутентификации: тот же класс, что в DRF.
        from apps.accounts.authentication import ActivityJWTAuthentication
        self.auth = ActivityJWTAuthentication()

    def __call__(self, request):
        if _should_enforce(request.path):
            response = self._check(request)
            if response is not None:
                return response
        return self.get_response(request)

    def _check(self, request):
        """Возвращает JsonResponse 403, если компания пользователя заморожена."""
        try:
            result = self.auth.authenticate(request)
        except Exception:
            # Невалидный/просроченный токен: пусть DRF сам отдаст 401.
            return None
        if result is None:
            return None
        user, _token = result
        if user is None or user.company_id is None:
            # Супер-админ не привязан к компании — гейт его не касается.
            return None

        sub = Subscription.objects.filter(company_id=user.company_id).first()
        if sub is None or sub.is_blocked:
            return JsonResponse(
                {
                    'detail': 'Подписка компании истекла. Продлите подписку, чтобы продолжить работу.',
                    'code': SUBSCRIPTION_EXPIRED_CODE,
                    'subscription': {
                        'status': sub.status if sub is not None else 'frozen',
                        'is_frozen': True,
                        'expires_at': sub.expires_at.isoformat() if sub is not None and sub.expires_at else None,
                    },
                },
                status=403,
            )
        return None
