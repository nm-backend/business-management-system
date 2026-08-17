"""
Админка компаний — SaaS-онбординг.

Создание компании в один шаг вместе с её владельцем (Owner), массовая
блокировка/разблокировка (каскадом на пользователей), просмотр состава
пользователей компании инлайном. Новая компания сразу получает триал-подписку
(30 дней) — как и при создании через API.
"""
from django import forms
from django.contrib import admin, messages
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404, render
from django.urls import path, reverse
from django.utils.html import format_html, format_html_join

from apps.accounts.access_keys import issue_access_key
from apps.accounts.models import AccessKey, Skill, User
from apps.core.admin_utils import badge, choice_badge
from .models import Company
from .subscriptions import activate_for_new_company

KEY_STATUS_COLORS = {'active': 'green', 'used': 'gray', 'revoked': 'red', 'expired': 'amber'}
SUBSCRIPTION_COLORS = {'active': 'green', 'grace': 'orange', 'expired': 'red', 'frozen': 'amber', 'cancelled': 'gray'}


class AddEmployeeForm(forms.Form):
    """Профессиональная форма создания сотрудника внутри компании."""
    first_name = forms.CharField(label='Имя', max_length=100)
    last_name = forms.CharField(label='Фамилия', max_length=100, required=False)
    username = forms.CharField(label='Логин', max_length=150,
                               help_text='Используется только внутри системы.')
    phone = forms.CharField(label='Телефон', max_length=20, required=False)
    role = forms.ChoiceField(label='Роль', choices=[
        (User.Role.WORKER, 'Ishchi (работник)'),
        (User.Role.ADMIN, 'Administrator (администратор)'),
    ], initial=User.Role.WORKER)
    position = forms.CharField(label='Должность', max_length=255, required=False)
    department = forms.CharField(label='Отдел', max_length=255, required=False)
    avatar = forms.ImageField(label='Аватар', required=False)
    birth_date = forms.DateField(label='Дата рождения', required=False,
                                 widget=forms.DateInput(attrs={'type': 'date'}))
    hire_date = forms.DateField(label='Дата найма', required=False,
                                widget=forms.DateInput(attrs={'type': 'date'}))
    status = forms.ChoiceField(label='Статус', choices=User.Status.choices,
                               initial=User.Status.ACTIVE)
    skills = forms.ModelMultipleChoiceField(
        label='Навыки', queryset=Skill.objects.none(), required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    bio = forms.CharField(label='О сотруднике', required=False,
                          widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        # Навыки — только каталог этой компании (изоляция).
        if company is not None:
            self.fields['skills'].queryset = Skill.objects.filter(company=company)

    def clean_username(self):
        username = self.cleaned_data['username']
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError('Пользователь с таким логином уже существует.')
        return username


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


class CompanyAccessKeyInline(admin.TabularInline):
    """Access Keys компании — код, сотрудник, статус (только просмотр)."""
    model = AccessKey
    fk_name = 'company'
    extra = 0
    fields = ('key', 'user', 'status_badge', 'expires_at', 'used_at', 'created_at')
    readonly_fields = fields
    can_delete = False
    verbose_name_plural = 'Access Keys (коды-приглашения)'

    def has_add_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')

    @admin.display(description='Статус')
    def status_badge(self, obj):
        return choice_badge(obj.effective_status, obj.effective_status.capitalize(), KEY_STATUS_COLORS)


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    form = CompanyAdminForm
    list_display = ('name', 'active_badge', 'subscription_badge', 'owner_display', 'users_count', 'employees_summary', 'created_at')
    list_filter = ('is_active', 'subscription_status')
    search_fields = ('name',)
    date_hierarchy = 'created_at'
    readonly_fields = (
        'created_at', 'updated_at', 'stats_panel', 'recent_activity',
        # Подпиской управляет супер-администратор через API — в админке только просмотр.
        'subscription_status', 'subscription_start', 'subscription_end', 'last_activity',
    )
    ordering = ('name',)
    inlines = [CompanyUserInline, CompanyAccessKeyInline]
    actions = ('block_companies', 'unblock_companies')

    def get_inlines(self, request, obj):
        # На странице создания инлайнов ещё нет.
        return [CompanyUserInline, CompanyAccessKeyInline] if obj else []

    # ── Add Employee: весь онбординг идёт со страницы компании ──
    def get_urls(self):
        custom = [
            path(
                '<int:company_id>/add-employee/',
                self.admin_site.admin_view(self.add_employee_view),
                name='companies_company_add_employee',
            ),
        ]
        return custom + super().get_urls()

    @transaction.atomic
    def add_employee_view(self, request, company_id):
        """Создаёт сотрудника этой компании и сразу выдаёт Access Key."""
        company = get_object_or_404(Company, pk=company_id)
        created_key = created_employee = None

        if request.method == 'POST':
            form = AddEmployeeForm(request.POST, request.FILES, company=company)
            if form.is_valid():
                cd = form.cleaned_data
                full_name = f"{cd['first_name']} {cd['last_name']}".strip()
                employee = User(
                    username=cd['username'],
                    full_name=full_name,
                    phone=cd.get('phone', ''),
                    role=cd['role'],
                    company=company,          # привязка к компании автоматически
                    position=cd.get('position', ''),
                    department=cd.get('department', ''),
                    birth_date=cd.get('birth_date'),
                    hire_date=cd.get('hire_date'),
                    status=cd['status'],
                    bio=cd.get('bio', ''),
                )
                if cd.get('avatar'):
                    employee.avatar = cd['avatar']
                employee.set_unusable_password()  # пароля нет — вход по Access Key
                employee.save()
                if cd.get('skills'):
                    employee.skills.set(cd['skills'])

                key = issue_access_key(user=employee, created_by=request.user)
                created_key = key.key
                created_employee = full_name or employee.username
                messages.success(request, f'Сотрудник «{created_employee}» создан. Access Key выдан.')
                form = AddEmployeeForm(company=company)  # чистая форма для следующего
        else:
            form = AddEmployeeForm(company=company)

        context = {
            **self.admin_site.each_context(request),
            'title': f'Новый сотрудник — {company.name}',
            'company': company,
            'form': form,
            'created_key': created_key,
            'created_employee': created_employee,
            'opts': self.model._meta,
        }
        return render(request, 'admin/companies/add_employee.html', context)

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return (
                (None, {'fields': ('name', 'is_active')}),
                ('Владелец (Owner)', {
                    'fields': ('owner_username', 'owner_password', 'owner_full_name', 'owner_phone'),
                    'description': 'Владелец будет создан вместе с компанией, а компания '
                                   'сразу получит триал-подписку (30 дней).',
                }),
            )
        return (
            (None, {'fields': ('name', 'is_active', 'created_at', 'updated_at')}),
            ('Подписка (SaaS)', {
                'fields': ('subscription_status', 'subscription_start', 'subscription_end', 'last_activity'),
                'description': 'Подпиской управляет платформенный супер-администратор '
                               'через API «Управление бизнесами». Здесь — только просмотр.',
            }),
            ('Обзор', {'fields': ('stats_panel', 'recent_activity')}),
        )

    @admin.display(description='Статус')
    def active_badge(self, obj):
        return badge('Активна', 'green') if obj.is_active else badge('Заблокирована', 'red')

    @admin.display(description='Подписка')
    def subscription_badge(self, obj):
        label = dict(Company.SubscriptionStatus.choices).get(
            obj.effective_subscription_status, obj.subscription_status,
        )
        return choice_badge(
            obj.effective_subscription_status, label, SUBSCRIPTION_COLORS,
        )

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
        add_url = reverse('admin:companies_company_add_employee', args=[obj.pk])
        return format_html(
            '<a href="{0}" style="display:inline-block;margin-bottom:14px;padding:9px 18px;'
            'background:#1c64d9;color:#fff;border-radius:8px;font-weight:600;'
            'text-decoration:none;">+ Добавить сотрудника</a>'
            '<table style="border-collapse:collapse;">{1}</table>',
            add_url, rows_html,
        )

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
            # SaaS: триал-подписка при создании (как и в API-пути).
            activate_for_new_company(obj)
            self.message_user(request, f'Компания и владелец «{owner.username}» созданы. Триал-подписка активирована.', messages.SUCCESS)

    def _set_active(self, request, queryset, active):
        for company in queryset:
            company.is_active = active
            company.save(update_fields=['is_active'])
            users = User.objects.filter(company=company)
            if active:
                # Разблокировка компании НЕ должна воскрешать сотрудников,
                # которых владелец заблокировал индивидуально (blocked_by_owner) —
                # так же, как в API-пути companies.views.toggle_active.
                users.filter(blocked_by_owner=False).update(is_active=True)
            else:
                users.update(is_active=False)
        verb = 'разблокированы' if active else 'заблокированы'
        self.message_user(request, f'{queryset.count()} компаний {verb} (вместе с пользователями).')

    @admin.action(description='Заблокировать компании (и их пользователей)')
    def block_companies(self, request, queryset):
        self._set_active(request, queryset, False)

    @admin.action(description='Разблокировать компании (и их пользователей)')
    def unblock_companies(self, request, queryset):
        self._set_active(request, queryset, True)
