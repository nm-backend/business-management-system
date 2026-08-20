from django.http import JsonResponse

GATE_API_PREFIX = '/api/v1/'

WHITELIST_PREFIXES = (
    '/api/v1/accounts/login/',
    '/api/v1/accounts/logout/',
    '/api/v1/accounts/token/refresh/',
    '/api/v1/accounts/me/',
    '/api/v1/accounts/access-key/',
    '/api/v1/accounts/push/',
    '/api/v1/companies/my-subscription',
    '/api/v1/billing/',
    '/api/v1/core/',
    '/api/v1/schema/',
    '/api/v1/swagger/',
    '/api/v1/redoc/',
)

SUBSCRIPTION_EXPIRED_CODE = 'subscription_expired'

_BLOCKED_STATUSES = frozenset({'expired', 'frozen', 'cancelled'})


def _should_enforce(path):
    if not path.startswith(GATE_API_PREFIX):
        return False
    return not path.startswith(WHITELIST_PREFIXES)


def _is_blocked(company):
    if company is None:
        return False, None, None
    status = company.effective_subscription_status
    if status in _BLOCKED_STATUSES:
        return True, status, company.subscription_end
    try:
        from .models import Subscription
        sub = Subscription.objects.filter(company_id=company.pk).first()
        if sub is not None and sub.is_blocked:
            return True, sub.status, sub.expires_at
    except Exception:
        pass
    return False, None, None


class SubscriptionGateMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if _should_enforce(request.path):
            response = self._check(request)
            if response is not None:
                return response
        return self.get_response(request)

    def _check(self, request):
        try:
            from apps.accounts.authentication import ActivityJWTAuthentication
            auth = ActivityJWTAuthentication()
            result = auth.authenticate(request)
        except Exception:
            return None
        if result is None:
            return None
        user, _token = result
        if user is None or user.company_id is None:
            return None

        company = getattr(user, 'company', None)
        blocked, status, expires_at = _is_blocked(company)
        if not blocked:
            return None

        return JsonResponse(
            {
                'detail': 'Подписка компании истекла. Продлите подписку, чтобы продолжить работу.',
                'code': SUBSCRIPTION_EXPIRED_CODE,
                'subscription': {
                    'status': status or 'frozen',
                    'is_frozen': True,
                    'expires_at': expires_at.isoformat() if expires_at else None,
                },
            },
            status=403,
        )
