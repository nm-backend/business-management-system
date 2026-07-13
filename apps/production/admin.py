"""Production admin."""
from django.contrib import admin

from .models import Task, WorkRecord


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ('id', 'company', 'worker', 'status', 'order', 'assigned_by', 'assigned_at')
    list_filter = ('company', 'status', 'assigned_at')
    search_fields = ('worker__username', 'worker__full_name', 'refusal_comment')
    autocomplete_fields = ('company', 'order', 'worker', 'assigned_by', 'confirmed_by')
    readonly_fields = ('assigned_at', 'accepted_at', 'completed_at', 'confirmed_at', 'created_at', 'updated_at')
    date_hierarchy = 'assigned_at'
    ordering = ('-assigned_at',)


@admin.register(WorkRecord)
class WorkRecordAdmin(admin.ModelAdmin):
    list_display = ('id', 'company', 'worker', 'product', 'quantity', 'status', 'labor_cost', 'created_at')
    list_filter = ('company', 'status', 'created_at')
    search_fields = ('worker__username', 'worker__full_name', 'comment', 'rejection_reason')
    autocomplete_fields = ('company', 'task', 'worker', 'product', 'confirmed_by')
    readonly_fields = ('confirmed_at', 'created_at', 'updated_at')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
