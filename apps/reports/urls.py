"""
URL configuration for reports API - аналитика и экспорт.
"""
from django.urls import path

from . import views

urlpatterns = [
    path('analytics/owner/', views.OwnerAnalyticsView.as_view(), name='analytics-owner'),
    path('analytics/admin/', views.AdminAnalyticsView.as_view(), name='analytics-admin'),
    path('export/finance/', views.OwnerFinanceExportView.as_view(), name='export-finance'),
    path('export/stock/', views.AdminStockExportView.as_view(), name='export-stock'),
    path('export/orders/', views.AdminOrdersExportView.as_view(), name='export-orders'),
    path('export/work/', views.AdminWorkExportView.as_view(), name='export-work'),
    path('export/', views.ExportReportAPIView.as_view(), name='export-general'),
]
