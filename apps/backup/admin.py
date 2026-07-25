from django.contrib import admin
from .models import BackupConfig, BackupLog


@admin.register(BackupConfig)
class BackupConfigAdmin(admin.ModelAdmin):
    list_display = ['company', 'is_enabled', 'schedule', 'storage', 'keep_last', 'created_at']
    list_filter = ['is_enabled', 'schedule', 'storage']
    search_fields = ['company__name']


@admin.register(BackupLog)
class BackupLogAdmin(admin.ModelAdmin):
    list_display = ['file_name', 'company', 'status', 'file_size', 'duration_seconds', 'created_at']
    list_filter = ['status', 'storage']
    search_fields = ['file_name', 'company__name']
    readonly_fields = ['file_name', 'file_size', 'status', 'error_message', 'duration_seconds', 'created_at']
