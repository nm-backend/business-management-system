from django.urls import path
from . import views

urlpatterns = [
    path('config/', views.BackupConfigView.as_view(), name='backup-config'),
    path('trigger/', views.BackupTriggerView.as_view(), name='backup-trigger'),
    path('logs/', views.BackupLogsView.as_view(), name='backup-logs'),
]
