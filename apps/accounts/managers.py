"""
Custom user manager for SkladPro.

Этот модуль содержит кастомный менеджер для модели User,
предоставляющий удобные методы для создания пользователей
и фильтрации по ролям.
"""
from django.contrib.auth.models import BaseUserManager


class UserManager(BaseUserManager):
    """
    Кастомный менеджер пользователей для SkladPro.

    Расширяет BaseUserManager для поддержки кастомной модели User
    с ролевой системой. Предоставляет методы для удобной работы
    с пользователями разных ролей.

    Методы:
        create_user(): создает обычного пользователя
        create_superuser(): создает суперпользователя (владельца)
        owners(): возвращает всех активных владельцев
        admins(): возвращает всех активных администраторов
        workers(): возвращает всех активных работников
    """

    def create_user(self, username, password=None, **extra_fields):
        """
        Создает и сохраняет пользователя с указанным username и password.

        Аргументы:
            username: str - уникальное имя пользователя
            password: str - пароль (опционально)
            **extra_fields: дополнительные поля модели User

        Возвращает:
            User - созданный пользователь

        Исключения:
            ValueError - если username не указан
        """
        if not username:
            raise ValueError('Username is required')
        user = self.model(username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra_fields):
        """
        Создает суперпользователя с правами администратора Django.

        Автоматически устанавливает:
        - is_staff=True (доступ к админке Django)
        - is_superuser=True (все права Django)
        - role='owner' (роль владельца в системе)

        Аргументы:
            username: str - уникальное имя пользователя
            password: str - пароль
            **extra_fields: дополнительные поля модели User

        Возвращает:
            User - созданный суперпользователь (владелец)
        """
        # Django-суперпользователь = платформенный супер-администратор:
        # управляет компаниями, сам к компании не привязан.
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', 'superadmin')
        extra_fields.setdefault('company', None)
        return self.create_user(username, password, **extra_fields)

    def owners(self):
        """
        Возвращает queryset всех активных владельцев.

        Возвращает:
            QuerySet - активные пользователи с role='owner'

        Используется для:
        - Проверки существования владельца при setup
        - Получения списка владельцев для отчетов
        """
        return self.filter(role='owner', is_active=True)

    def admins(self):
        """
        Возвращает queryset всех активных администраторов.

        Возвращает:
            QuerySet - активные пользователи с role='admin'

        Используется для:
        - Получения списка администраторов
        - Фильтрации пользователей по роли
        """
        return self.filter(role='admin', is_active=True)

    def workers(self):
        """
        Возвращает queryset всех активных работников.

        Возвращает:
            QuerySet - активные пользователи с role='worker'

        Используется для:
        - Получения списка работников
        - Расчета зарплат и статистики
        - Назначения задач
        """
        return self.filter(role='worker', is_active=True)
