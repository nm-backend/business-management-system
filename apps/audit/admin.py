from django.contrib import admin
from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = [
        'created_at',
        'company',
        'actor_username',
        'actor_role',
        'action',
        'object_type',
        'object_id',
        'ip_address',
    ]
    list_filter = ['company', 'action', 'actor_role', 'object_type', 'created_at']
    search_fields = ['actor_username', 'object_repr', 'object_id']
    date_hierarchy = 'created_at'
    readonly_fields = [
        'company',
        'actor',
        'actor_username',
        'actor_role',
        'action',
        'object_type',
        'object_id',
        'object_repr',
        'changes',
        'metadata',
        'ip_address',
        'user_agent',
        'created_at',
        'updated_at',
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
