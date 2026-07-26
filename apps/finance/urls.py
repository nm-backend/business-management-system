"""
URL configuration for finance API.

Этот модуль содержит URL routing для API управления финансами.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ExpenseViewSet, LaborRateViewSet, WorkerPaymentViewSet, AnalyticsView

router = DefaultRouter()
router.register(r'expenses', ExpenseViewSet, basename='expense')
router.register(r'labor-rates', LaborRateViewSet, basename='laborrate')
router.register(r'worker-payments', WorkerPaymentViewSet, basename='workerpayment')

urlpatterns = [
    path('', include(router.urls)),
    path('analytics/', AnalyticsView.as_view(), name='finance-analytics'),
]
