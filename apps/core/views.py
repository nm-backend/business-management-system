from django.db import connection
from django.http import JsonResponse
from rest_framework import permissions, viewsets
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from apps.core.permissions import IsSuperAdmin
from core.utils import get_locale
from .models import Currency, ExchangeRate
from .serializers import CurrencySerializer, ExchangeRateSerializer


class GlobalReferenceWriteMixin:
    """
    Currency и ExchangeRate — ГЛОБАЛЬНЫЕ справочники (без company), общие для
    всех компаний. Чтение — любому аутентифицированному (компаниям нужны валюты
    для отображения), а запись/удаление — только платформенному супер-админу.
    Раньше был открытый ModelViewSet с [IsAuthenticated]: работник любой компании
    мог создавать/менять/удалять валюты и курсы, влияя на все компании (BAC).
    """
    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsSuperAdmin()]


class CompanyScopedViewSet(viewsets.ModelViewSet):
    """
    Базовый ViewSet для моделей, зависящих от компании (Company).
    Автоматически фильтрует queryset по company_id текущего пользователя.
    """
    def get_queryset(self):
        return self.queryset.filter(company_id=self.request.user.company_id)


class HealthView(APIView):
    """
    Health-check для мониторинга/оркестратора: живо ли приложение и доступна ли БД.

    GET /api/v1/core/health/ -> 200 {"status":"ok","database":true}
    Если БД недоступна -> 503 {"status":"degraded","database":false}.
    Публичный и без аутентификации: балансировщик/Docker healthcheck дергают его
    без токена. Никаких чувствительных данных не отдаёт.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    # Health не троттлим: оркестратор/LB (Render healthCheckPath, k8s probe) бьют
    # его часто; троттлинг вернул бы 429 и пометил живой сервис как unhealthy.
    throttle_classes = []

    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
                cursor.fetchone()
            db_ok = True
        except Exception:
            db_ok = False
        return JsonResponse(
            {'status': 'ok' if db_ok else 'degraded', 'database': db_ok},
            status=200 if db_ok else 503,
        )

class CurrencyViewSet(GlobalReferenceWriteMixin, viewsets.ModelViewSet):
    queryset = Currency.objects.filter(is_active=True)
    serializer_class = CurrencySerializer

class ExchangeRateViewSet(GlobalReferenceWriteMixin, viewsets.ModelViewSet):
    # select_related убирает N+1: сериализатор отдаёт from/to_currency.code.
    queryset = ExchangeRate.objects.select_related('from_currency', 'to_currency')
    serializer_class = ExchangeRateSerializer

class LocaleView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, lang_code):
        allowed_languages = ['uz_cyrl', 'ru']
        if lang_code not in allowed_languages:
            return JsonResponse({'error': 'Language not supported'}, status=400)

        data = get_locale(lang_code)
        return JsonResponse(data, json_dumps_params={'ensure_ascii': False})
