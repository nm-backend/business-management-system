"""
Админка компаний — SaaS-онбординг.

Создание компании в один шаг вместе с её владельцем (Owner), массовая
блокировка/разблокировка (каскадом на пользователей), просмотр состава
пользователей компании инлайном.
"""
from django import forms
from django.contrib import admin, messages
from django.db import transaction
from django.db.models import Count
from django.utils.html import format_html, format_html_join

from apps.accounts.models import AccessKey, User
from apps.core.admin_utils import badge
from .models import Company


class CompanyAdminForm(forms.ModelForm):
    """Форма компании с полями владельца (заполняются при создании)."""
    owner_username = forms.CharField(
        required=False, label='Owner: логин',
        help_text='Заполните при создании новой компании, чтобы сразу создать владельца.',
    )
    owner_password = forms.CharField(
        required=False, label='Owner: пароль', widget=forms.PasswordInput(render_value=False),
    )
    owner_full_name = forms.CharField(required=False, label='Owner: полное имя')
    owner_phone = forms.CharField(required=False, label='Owner: телефон')

    class Meta:
        model = Company
        fields = ['name', 'is_active']

    def clean(self):
        cleaned = super().clean()
        # На создании владелец обязателен; при редактировании поля игнорируются.
        if self.instance.pk is None:
            if not cleaned.get('owner_username') or not cleaned.get('owner_password'):
                raise forms.ValidationError('Укажите логин и пароль владельца новой компании.')
            if User.objects.filter(username=cleaned['owner_username']).exists():
                raise forms.ValidationError('Пользователь с таким логином уже существует.')
        return cleaned


class CompanyUserInline(admin.TabularInline):
    """Пользователи компании (только просмотр — управление через раздел Users)."""
    model = User
    fields = ('username', 'full_name', 'role', 'is_active')
    readonly_fields = fields
    extra = 0
    can_delete = False
    show_change_link = True
    verbose_name_plural = 'Пользователи компании'

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    form = CompanyAdminForm
    list_display = ('name', 'active_badge', 'owner_display', 'users_count', 'employees_summary', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name',)
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at', 'updated_at', 'stats_panel', 'recent_activity')
    ordering = ('name',)
    inlines = [CompanyUserInline]
    actions = ('block_companies', 'unblock_companies')

    def get_inlines(self, request, obj):
        # На странице создания инлайна пользователей ещё нет.
        return [CompanyUserInline] if obj else []

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return (
                (None, {'fields': ('name', 'is_active')}),
                ('Владелец (Owner)', {
                    'fields': ('owner_username', 'owner_password', 'owner_full_name', 'owner_phone'),
                    'description': 'Владелец будет создан вместе с компанией.',
                }),
            )
        return (
            (None, {'fields': ('name', 'is_active', 'created_at', 'updated_at')}),
            ('Обзор', {'fields': ('stats_panel', 'recent_activity')}),
        )

    @admin.display(description='Статус')
    def active_badge(self, obj):
        return badge('Активна', 'green') if obj.is_active else badge('Заблокирована', 'red')

    @admin.display(description='Владелец')
    def owner_display(self, obj):
        owner = obj.users.filter(role=User.Role.OWNER).first()
        return owner.full_name or owner.username if owner else '—'

    @admin.display(description='Пользователи')
    def users_count(self, obj):
        return obj.users.count()

    @admin.display(description='Состав')
    def employees_summary(self, obj):
        counts = {
            row['role']: row['n']
            for row in obj.users.values('role').annotate(n=Count('id'))
        }
        parts = []
        for role, label, color in (
            (User.Role.OWNER, 'вл', 'blue'),
            (User.Role.ADMIN, 'адм', 'teal'),
            (User.Role.WORKER, 'раб', 'gray'),
        ):
            if counts.get(role):
                parts.append(f'{counts[role]} {label}')
        return badge(' · '.join(parts), 'gray') if parts else '—'

    @admin.display(description='Статистика')
    def stats_panel(self, obj):
        if obj.pk is None:
            return '—'
        users = obj.users.all()
        roles = {r['role']: r['n'] for r in users.values('role').annotate(n=Count('id'))}
        active_keys = AccessKey.objects.filter(company=obj, status=AccessKey.Status.ACTIVE).count()
        skills = obj.skills.count()
        rows = [
            ('Владелец', roles.get(User.Role.OWNER, 0)),
            ('Администраторы', roles.get(User.Role.ADMIN, 0)),
            ('Работники', roles.get(User.Role.WORKER, 0)),
            ('Активных сотрудников', users.filter(is_active=True).count()),
            ('Активных Access Key', active_keys),
            ('Навыков в каталоге', skills),
            ('Клиентов', obj.clients.count()),
            ('Заказов', obj.orders.count()),
        ]
        rows_html = format_html_join(
            '',
            '<tr><td style="padding:3px 16px 3px 0;color:#5a6472;">{}</td>'
            '<td style="padding:3px 0;font-weight:700;">{}</td></tr>',
            rows,
        )
        return format_html('<table style="border-collapse:collapse;">{}</table>', rows_html)

    @admin.display(description='Недавняя активность')
    def recent_activity(self, obj):
        if obj.pk is None:
            return '—'
        from apps.audit.models import AuditLog
        logs = (
            AuditLog.objects.filter(company=obj)
            .order_by('-created_at')[:8]
        )
        if not logs:
            return format_html('<span style="color:#8a919e;">Пока нет записей</span>')
        items = format_html_join(
            '',
            '<li style="margin-bottom:4px;"><span style="color:#8a919e;">{}</span> '
            '<b>{}</b> {} <span style="color:#5a6472;">{}</span></li>',
            (
                (
                    log.created_at.strftime('%d.%m %H:%M'),
                    log.actor_username or 'system',
                    log.action,
                    log.object_repr or log.object_type,
                )
                for log in logs
            ),
        )
        return format_html('<ul style="margin:0;padding-left:16px;">{}</ul>', items)

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        creating = obj.pk is None
        super().save_model(request, obj, form, change)
        if creating:
            owner = User(
                username=form.cleaned_data['owner_username'],
                full_name=form.cleaned_data.get('owner_full_name', ''),
                phone=form.cleaned_data.get('owner_phone', ''),
                role=User.Role.OWNER,
                company=obj,
            )
            owner.set_password(form.cleaned_data['owner_password'])
            owner.save()
            self.message_user(request, f'Компания и владелец «{owner.username}» созданы.', messages.SUCCESS)

    def _set_active(self, request, queryset, active):
        for company in queryset:
            company.is_active = active
            company.save(update_fields=['is_active'])
            User.objects.filter(company=company).update(is_active=active)
        verb = 'разблокированы' if active else 'заблокированы'
        self.message_user(request, f'{queryset.count()} компаний {verb} (вместе с пользователями).')

    @admin.action(description='Заблокировать компании (и их пользователей)')
    def block_companies(self, request, queryset):
        self._set_active(request, queryset, False)

    @admin.action(description='Разблокировать компании (и их пользователей)')
    def unblock_companies(self, request, queryset):
        self._set_active(request, queryset, True)
