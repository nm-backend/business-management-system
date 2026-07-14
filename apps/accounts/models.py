"""
Custom User model with role-based access control.

Этот модуль содержит кастомную модель пользователя, которая расширяет
AbstractUser для поддержки ролевой системы и дополнительных полей,
необходимых для бизнес-логики SkladPro.

Ролевая система:
- owner: владелец бизнеса (полный доступ)
- admin: администратор (управление складом и работниками)
- worker: работник (ограниченный доступ)
"""
from django.contrib.auth.models import AbstractUser
from django.db import models

from apps.core.models import TimestampedModel

from .managers import UserManager


class Skill(TimestampedModel):
    """
    Профессиональный навык сотрудника (Python, Sales, Manager, Designer и т.д.).

    Каталог навыков компании. Навык привязан к компании (арендатору), поэтому
    одна компания НИКОГДА не видит навыки другой. Изоляция обеспечивается на
    уровне queryset во view (SkillViewSet.get_queryset фильтрует по
    request.user.company_id) и проверяется тестами изоляции.

    Поля:
        company: ForeignKey - компания-владелец (арендатор). Ключ изоляции.
        name: CharField - название навыка (уникально в рамках компании).
        category: CharField - необязательная категория для группировки
                  (например: «Технологии», «Продажи»).

    Особенности:
        - Наследует TimestampedModel (created_at/updated_at).
        - Уникальность имени в пределах компании (две разные компании могут
          иметь навык с одинаковым именем).
    """
    company = models.ForeignKey(
        'companies.Company',
        on_delete=models.CASCADE,
        null=True,
        related_name='skills',
    )
    name = models.CharField(max_length=100)
    category = models.CharField(max_length=50, blank=True, default='')

    class Meta:
        verbose_name = 'Skill'
        verbose_name_plural = 'Skills'
        ordering = ['name']
        constraints = [
            # Имя навыка уникально в пределах компании, но не глобально.
            models.UniqueConstraint(
                fields=['company', 'name'],
                name='accounts_skill_unique_per_company',
            ),
        ]
        indexes = [
            models.Index(fields=['company', 'name']),
        ]

    def __str__(self):
        """Строковое представление навыка — его название."""
        return self.name


class User(AbstractUser):
    """
    Кастомная модель пользователя с ролевой системой.

    Расширяет стандартную Django модель AbstractUser дополнительными
    полями для бизнес-логики и системой контроля доступа на основе ролей.

    Поля:
        email: EmailField - email пользователя (опционально)
        role: CharField - роль пользователя (owner/admin/worker)
        phone: CharField - телефон (опционально)
        full_name: CharField - полное имя
        avatar: ImageField - аватар пользователя
        language: CharField - предпочитаемый язык (uz_cyrl/ru)
        can_write_to_owner: BooleanField - может ли писать владельцу
        can_create_workers: BooleanField - может ли создавать работников
        can_see_other_workers: BooleanField - может ли видеть других работников
        created_at: DateTimeField - время создания аккаунта
        updated_at: DateTimeField - время последнего обновления

    Свойства:
        is_owner: bool - True если роль owner
        is_admin: bool - True если роль admin
        is_worker: bool - True если роль worker
        display_role: str - отображаемое название роли
    """

    class Role(models.TextChoices):
        """
        Роли пользователей в системе.

        SUPERADMIN: платформенный супер-администратор - управляет компаниями,
                    не привязан к компании, не видит бизнес-данные.
        OWNER: владелец бизнеса - полный доступ ко всем данным своей компании
        ADMIN: администратор - управление складом и работниками своей компании
        WORKER: работник - ограниченный доступ для выполнения задач
        """
        SUPERADMIN = 'superadmin', 'Super Administrator'
        OWNER = 'owner', 'Egasi'
        ADMIN = 'admin', 'Administrator'
        WORKER = 'worker', 'Ishchi'

    class Language(models.TextChoices):
        """
        Поддерживаемые языки интерфейса.

        UZBEK: узбекский (кириллица) - основной язык
        RUSSIAN: русский - дополнительный язык
        """
        UZBEK = 'uz_cyrl', 'Ўзбекча'
        RUSSIAN = 'ru', 'Русский'

    class Status(models.TextChoices):
        """
        Кадровый статус сотрудника (НЕ путать с is_active — блокировкой входа).

        ACTIVE: работает
        ON_LEAVE: в отпуске
        SUSPENDED: временно отстранён
        """
        ACTIVE = 'active', 'Faol'
        ON_LEAVE = 'on_leave', 'Taʼtilda'
        SUSPENDED = 'suspended', 'Toʼxtatilgan'

    # Компания (арендатор). None только для платформенного супер-администратора.
    company = models.ForeignKey(
        'companies.Company',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='users',
    )

    # Основные поля профиля
    email = models.EmailField(blank=True, default='')
    role = models.CharField(max_length=12, choices=Role.choices, default=Role.WORKER, db_index=True)
    phone = models.CharField(max_length=20, blank=True, default='')
    full_name = models.CharField(max_length=255, blank=True, default='')
    avatar = models.ImageField(upload_to='avatars/', blank=True, default='')
    language = models.CharField(max_length=10, choices=Language.choices, default=Language.UZBEK)

    # Расширенный профиль сотрудника
    position = models.CharField(max_length=255, blank=True, default='')      # должность
    department = models.CharField(max_length=255, blank=True, default='')    # отдел
    birth_date = models.DateField(null=True, blank=True)                     # дата рождения (опц.)
    hire_date = models.DateField(null=True, blank=True)                      # дата найма
    bio = models.TextField(blank=True, default='')                          # о себе
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True,
    )
    last_activity = models.DateTimeField(null=True, blank=True)              # последняя активность

    # Профессиональные навыки (каталог навыков компании)
    skills = models.ManyToManyField('Skill', blank=True, related_name='employees')

    # Дополнительные права для администраторов
    can_write_to_owner = models.BooleanField(default=False)
    can_create_workers = models.BooleanField(default=False)
    can_see_other_workers = models.BooleanField(default=False)

    # Временные метки
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Кастомный менеджер
    objects = UserManager()

    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        ordering = ['-created_at']
        constraints = [
            # Ровно один владелец на компанию (а не один на всю систему).
            models.UniqueConstraint(
                fields=['company'],
                condition=models.Q(role='owner'),
                name='accounts_single_owner_per_company',
            ),
        ]

    def __str__(self):
        """
        Строковое представление пользователя.

        Возвращает полное имя если оно указано, иначе username.
        """
        return self.full_name or self.username

    @property
    def is_superadmin(self):
        """
        Проверяет, является ли пользователь платформенным супер-администратором.

        Возвращает:
            bool - True если role == 'superadmin'
        """
        return self.role == self.Role.SUPERADMIN

    @property
    def is_owner(self):
        """
        Проверяет, является ли пользователь владельцем.

        Возвращает:
            bool - True если role == 'owner'
        """
        return self.role == self.Role.OWNER

    @property
    def is_admin(self):
        """
        Проверяет, является ли пользователь администратором.

        Возвращает:
            bool - True если role == 'admin'
        """
        return self.role == self.Role.ADMIN

    @property
    def is_worker(self):
        """
        Проверяет, является ли пользователь работником.

        Возвращает:
            bool - True если role == 'worker'
        """
        return self.role == self.Role.WORKER

    @property
    def display_role(self):
        """
        Возвращает отображаемое название роли.

        Возвращает:
            str - человекочитаемое название роли на текущем языке
        """
        return dict(self.Role.choices).get(self.role, self.role)
