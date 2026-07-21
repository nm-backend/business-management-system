from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CurrencyViewSet, ExchangeRateViewSet, HealthView, LocaleView

router = DefaultRouter()
router.register(r'currencies', CurrencyViewSet, basename='currency')
router.register(r'exchange-rates', ExchangeRateViewSet, basename='exchange-rate')

urlpatterns = [
    path('', include(router.urls)),
    path('health/', HealthView.as_view(), name='health'),
    path('locale/<str:lang_code>/', LocaleView.as_view(), name='locale'),
]
