from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('username', 'full_name', 'company', 'role', 'phone', 'is_active', 'created_at')
    list_filter = ('company', 'role', 'is_active', 'language')
    search_fields = ('username', 'full_name', 'phone')
    autocomplete_fields = ('company',)
    ordering = ('-created_at',)
    date_hierarchy = 'created_at'

    fieldsets = BaseUserAdmin.fieldsets + (
        ('Компания и роль', {
            'fields': ('company', 'role', 'full_name', 'phone', 'avatar', 'language'),
        }),
        ('Дополнительные права', {
            'fields': ('can_write_to_owner', 'can_create_workers', 'can_see_other_workers'),
        }),
    )

    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ('Компания и роль', {
            'fields': ('company', 'role', 'full_name', 'phone'),
        }),
    )
