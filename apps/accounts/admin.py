from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ['username', 'full_name', 'role', 'phone', 'is_active', 'created_at']
    list_filter = ['role', 'is_active', 'language']
    search_fields = ['username', 'full_name', 'phone']
    ordering = ['-created_at']

    fieldsets = BaseUserAdmin.fieldsets + (
        ('Profile', {
            'fields': ('role', 'full_name', 'phone', 'avatar', 'language'),
        }),
        ('Custom Permissions', {
            'fields': ('can_write_to_owner', 'can_create_workers', 'can_see_other_workers'),
        }),
    )

    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ('Profile', {
            'fields': ('role', 'full_name', 'phone'),
        }),
    )
