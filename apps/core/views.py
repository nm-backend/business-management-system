import json
from pathlib import Path
from django.conf import settings
from django.http import JsonResponse
from rest_framework import viewsets
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from .models import Currency, ExchangeRate
from .serializers import CurrencySerializer, ExchangeRateSerializer

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

        locale_dir = Path(settings.BASE_DIR) / 'locale'
        locale_file = locale_dir / f'{lang_code}.json'

        if not locale_file.exists():
            return JsonResponse({'error': 'Locale file not found'}, status=404)

        with open(locale_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        return JsonResponse(data, json_dumps_params={'ensure_ascii': False})
