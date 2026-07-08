from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CurrencyViewSet, ExchangeRateViewSet, LocaleView

router = DefaultRouter()
router.register(r'currencies', CurrencyViewSet, basename='currency')
router.register(r'exchange-rates', ExchangeRateViewSet, basename='exchange-rate')

urlpatterns = [
    path('', include(router.urls)),
    path('locale/<str:lang_code>/', LocaleView.as_view(), name='locale'),
]
