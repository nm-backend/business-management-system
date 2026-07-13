"""
Админка компаний — SaaS-онбординг.

Создание компании в один шаг вместе с её владельцем (Owner), массовая
блокировка/разблокировка (каскадом на пользователей), просмотр состава
пользователей компании инлайном.
"""
from django import forms
from django.contrib import admin, messages
from django.db import transaction

from apps.accounts.models import User
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
    list_display = ('name', 'is_active', 'owner_display', 'users_count', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name',)
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at', 'updated_at')
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
        return ((None, {'fields': ('name', 'is_active', 'created_at', 'updated_at')}),)

    @admin.display(description='Владелец')
    def owner_display(self, obj):
        owner = obj.users.filter(role=User.Role.OWNER).first()
        return owner.full_name or owner.username if owner else '—'

    @admin.display(description='Пользователи')
    def users_count(self, obj):
        return obj.users.count()

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
