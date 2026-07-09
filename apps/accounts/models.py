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
from .managers import UserManager


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

        OWNER: владелец бизнеса - полный доступ ко всем данным
        ADMIN: администратор - управление складом и работниками
        WORKER: работник - ограниченный доступ для выполнения задач
        """
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

    # Основные поля профиля
    email = models.EmailField(blank=True, default='')
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.WORKER, db_index=True)
    phone = models.CharField(max_length=20, blank=True, default='')
    full_name = models.CharField(max_length=255, blank=True, default='')
    avatar = models.ImageField(upload_to='avatars/', blank=True, default='')
    language = models.CharField(max_length=10, choices=Language.choices, default=Language.UZBEK)

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

    def __str__(self):
        """
        Строковое представление пользователя.

        Возвращает полное имя если оно указано, иначе username.
        """
        return self.full_name or self.username

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
