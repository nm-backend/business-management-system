from django.http import JsonResponse
from rest_framework import viewsets
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from core.utils import get_locale
from core.permissions import IsOwner
from .models import Currency, ExchangeRate
from .serializers import CurrencySerializer, ExchangeRateSerializer

class CurrencyViewSet(viewsets.ModelViewSet):
    queryset = Currency.objects.filter(is_active=True)
    serializer_class = CurrencySerializer
    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            return [IsOwner()]
        return [IsAuthenticated()]

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed('DELETE', detail='Currency deletion is prohibited.')

class ExchangeRateViewSet(viewsets.ModelViewSet):
    queryset = ExchangeRate.objects.all()
    serializer_class = ExchangeRateSerializer
    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            return [IsOwner()]
        return [IsAuthenticated()]

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed('DELETE', detail='Exchange-rate deletion is prohibited.')

class LocaleView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, lang_code):
        allowed_languages = ['uz_cyrl', 'ru']
        if lang_code not in allowed_languages:
            return JsonResponse({'error': 'Language not supported'}, status=400)

        data = get_locale(lang_code)
        return JsonResponse(data, json_dumps_params={'ensure_ascii': False})
