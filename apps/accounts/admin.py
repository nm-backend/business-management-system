"""
Админка сотрудников: пользователи, навыки и Access Key (коды-приглашения).

Панель управления ERP: цветные бейджи ролей/статусов, навыки, встроенное
управление Access Key (генерация/отзыв/статус), оптимизированные запросы.
"""
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils import timezone

from apps.core.admin_utils import badge, choice_badge

from .access_keys import issue_access_key, revoke_access_key
from .models import AccessKey, Skill, User

ROLE_COLORS = {'superadmin': 'purple', 'owner': 'blue', 'admin': 'teal', 'worker': 'gray'}
STATUS_COLORS = {'active': 'green', 'on_leave': 'amber', 'suspended': 'red'}
KEY_STATUS_COLORS = {'active': 'green', 'used': 'gray', 'revoked': 'red', 'expired': 'amber'}


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'company', 'employee_count', 'created_at')
    list_filter = ('company', 'category')
    search_fields = ('name', 'category')
    autocomplete_fields = ('company',)
    ordering = ('company', 'name')

    def get_queryset(self, request):
        from django.db.models import Count
        return super().get_queryset(request).select_related('company').annotate(
            _emp_count=Count('employees', distinct=True),
        )

    @admin.display(description='Сотрудников', ordering='_emp_count')
    def employee_count(self, obj):
        return obj._emp_count


class AccessKeyInline(admin.TabularInline):
    """Ключи-приглашения сотрудника (просмотр + статус)."""
    model = AccessKey
    fk_name = 'user'
    extra = 0
    fields = ('key', 'status_badge', 'expires_at', 'used_at', 'created_at')
    readonly_fields = ('key', 'status_badge', 'expires_at', 'used_at', 'created_at')
    can_delete = False
    verbose_name_plural = 'Access Keys (коды-приглашения)'

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description='Статус')
    def status_badge(self, obj):
        return choice_badge(obj.effective_status, obj.effective_status.capitalize(), KEY_STATUS_COLORS)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        'username', 'full_name', 'company', 'role_badge', 'status_badge',
        'department', 'is_active', 'last_activity',
    )
    list_filter = ('company', 'role', 'status', 'is_active', 'language', 'department')
    search_fields = ('username', 'full_name', 'phone', 'position', 'department', 'email')
    autocomplete_fields = ('company',)
    filter_horizontal = ('skills', 'groups', 'user_permissions')
    ordering = ('-created_at',)
    date_hierarchy = 'created_at'
    list_select_related = ('company',)
    readonly_fields = ('last_activity', 'created_at', 'updated_at')
    inlines = (AccessKeyInline,)
    actions = ('activate_users', 'deactivate_users', 'generate_access_keys')

    @admin.display(description='Роль', ordering='role')
    def role_badge(self, obj):
        return choice_badge(obj.role, obj.display_role, ROLE_COLORS)

    @admin.display(description='Кадровый статус', ordering='status')
    def status_badge(self, obj):
        return choice_badge(obj.status, obj.get_status_display(), STATUS_COLORS)

    @admin.action(description='Разблокировать выбранных пользователей')
    def activate_users(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} пользователей разблокировано.')

    @admin.action(description='Заблокировать выбранных пользователей')
    def deactivate_users(self, request, queryset):
        # Владельцев массово не блокируем — у компании должен остаться владелец.
        updated = queryset.exclude(role=User.Role.OWNER).update(is_active=False)
        self.message_user(request, f'{updated} пользователей заблокировано (владельцы пропущены).')

    @admin.action(description='Сгенерировать Access Key для выбранных сотрудников')
    def generate_access_keys(self, request, queryset):
        issued = 0
        skipped = 0
        for user in queryset:
            if user.is_owner or user.is_superadmin or user.company_id is None:
                skipped += 1
                continue
            issue_access_key(user=user, created_by=request.user)
            issued += 1
        msg = f'Выпущено ключей: {issued}.'
        if skipped:
            msg += f' Пропущено (владелец/супер-админ/без компании): {skipped}.'
        self.message_user(request, msg, messages.SUCCESS if issued else messages.WARNING)

    fieldsets = BaseUserAdmin.fieldsets + (
        ('Компания и роль', {
            'fields': ('company', 'role', 'full_name', 'phone', 'avatar', 'language'),
        }),
        ('Профиль сотрудника', {
            'fields': ('position', 'department', 'birth_date', 'hire_date', 'status', 'bio', 'skills', 'last_activity'),
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


@admin.register(AccessKey)
class AccessKeyAdmin(admin.ModelAdmin):
    list_display = ('key_code', 'employee', 'company', 'status_badge', 'expires_at', 'used_at', 'created_at')
    list_filter = ('company', 'status', 'created_at')
    search_fields = ('key', 'user__username', 'user__full_name')
    autocomplete_fields = ('company', 'user', 'created_by')
    readonly_fields = ('key', 'used_at', 'created_at', 'updated_at')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    list_select_related = ('company', 'user')
    actions = ('revoke_keys', 'regenerate_keys')

    @admin.display(description='Код (копируйте)', ordering='key')
    def key_code(self, obj):
        # Моноширинный, легко выделить и скопировать.
        return badge(obj.key, 'blue')

    @admin.display(description='Сотрудник', ordering='user')
    def employee(self, obj):
        return obj.user.full_name or obj.user.username

    @admin.display(description='Статус')
    def status_badge(self, obj):
        return choice_badge(obj.effective_status, obj.effective_status.capitalize(), KEY_STATUS_COLORS)

    @admin.action(description='Отозвать выбранные ключи')
    def revoke_keys(self, request, queryset):
        count = 0
        for key in queryset.filter(status=AccessKey.Status.ACTIVE):
            revoke_access_key(key)
            count += 1
        self.message_user(request, f'Отозвано ключей: {count}.')

    @admin.action(description='Перевыпустить ключи (новый код, старый отзывается)')
    def regenerate_keys(self, request, queryset):
        count = 0
        for key in queryset.select_related('user'):
            if key.user.is_owner or key.user.company_id is None:
                continue
            issue_access_key(user=key.user, created_by=request.user)
            count += 1
        self.message_user(request, f'Перевыпущено ключей: {count}.')
