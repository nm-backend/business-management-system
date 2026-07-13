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
    actions = ('activate_users', 'deactivate_users')

    @admin.action(description='Разблокировать выбранных пользователей')
    def activate_users(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} пользователей разблокировано.')

    @admin.action(description='Заблокировать выбранных пользователей')
    def deactivate_users(self, request, queryset):
        # Владельцев не блокируем массово — у компании должен остаться владелец.
        updated = queryset.exclude(role=User.Role.OWNER).update(is_active=False)
        self.message_user(request, f'{updated} пользователей заблокировано (владельцы пропущены).')

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
