from django.db import connection
from django.http import JsonResponse
from rest_framework import viewsets
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from core.utils import get_locale
from .models import Currency, ExchangeRate
from .serializers import CurrencySerializer, ExchangeRateSerializer


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

class CurrencyViewSet(viewsets.ModelViewSet):
    queryset = Currency.objects.filter(is_active=True)
    serializer_class = CurrencySerializer
    permission_classes = [IsAuthenticated]

class ExchangeRateViewSet(viewsets.ModelViewSet):
    queryset = ExchangeRate.objects.all()
    serializer_class = ExchangeRateSerializer
    permission_classes = [IsAuthenticated]

class LocaleView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, lang_code):
        allowed_languages = ['uz_cyrl', 'ru']
        if lang_code not in allowed_languages:
            return JsonResponse({'error': 'Language not supported'}, status=400)

        data = get_locale(lang_code)
        return JsonResponse(data, json_dumps_params={'ensure_ascii': False})
