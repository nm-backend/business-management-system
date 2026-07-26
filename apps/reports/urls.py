"""
URL configuration for reports API.

Endpoints:
- GET /financial/ — финансовый отчёт (owner, PDF/Excel)
- GET /operational/ — операционный отчёт (admin, PDF/Excel)
"""
from django.urls import path
from .views import FinancialReportView, OperationalReportView

urlpatterns = [
    path('financial/', FinancialReportView.as_view(), name='report-financial'),
    path('operational/', OperationalReportView.as_view(), name='report-operational'),
]
