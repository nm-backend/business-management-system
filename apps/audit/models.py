"""
Audit models - система аудита и логирования действий.

Этот модуль содержит модель для записи всех действий пользователей в системе.
Аудит логи необходимы для безопасности и отслеживания истории изменений.

ВАЖНО: Audit logs доступны только владельцу (owner) для чтения.
Записи создаются автоматически системой и не могут быть изменены.
"""
from django.conf import settings
from django.db import models
from apps.core.models import TimestampedModel


class AuditLog(TimestampedModel):
    """
    Модель записи аудита действий пользователей.

    Хранит детальную информацию о всех действиях в системе для
    обеспечения безопасности и возможности восстановления истории.
    Записи создаются автоматически и доступны только владельцу.

    Поля:
        actor: ForeignKey - пользователь, выполнивший действие (SET_NULL при удалении)
        actor_username: CharField - имя пользователя (сохраняется при удалении)
        actor_role: CharField - роль пользователя в момент действия
        action: CharField - тип действия (создание, обновление, удаление и т.д.)
        object_type: CharField - тип измененного объекта (например: 'User', 'RawMaterial')
        object_id: CharField - ID измененного объекта
        object_repr: CharField - строковое представление объекта
        changes: JSONField - изменения полей (старые и новые значения)
        metadata: JSONField - дополнительная информация о действии
        ip_address: GenericIPAddressField - IP адрес пользователя
        user_agent: TextField - User Agent браузера

    Особенности:
        - Автоматические временные метки (TimestampedModel)
        - SET_NULL для actor (сохраняется actor_username)
        - Индексы для быстрого поиска по action, object_type, actor_role
        - JSONField для хранения сложных данных (changes, metadata)
    """

    class Action(models.TextChoices):
        """
        Типы действий, которые записываются в audit log.

        SETUP_OWNER: создание владельца системы
        LOGIN: вход пользователя
        LOGOUT: выход пользователя
        CREATE: создание объекта
        UPDATE: обновление объекта
        ARCHIVE: архивация объекта
        ACTIVATE: активация пользователя
        DEACTIVATE: деактивация пользователя
        RESET_PASSWORD: сброс пароля администратором
        CHANGE_PASSWORD: смена пароля пользователем
        CHANGE_LANGUAGE: смена языка интерфейса
        """
        SETUP_OWNER = 'setup_owner', 'Setup owner'
        LOGIN = 'login', 'Login'
        LOGOUT = 'logout', 'Logout'
        CREATE = 'create', 'Create'
        UPDATE = 'update', 'Update'
        ARCHIVE = 'archive', 'Archive'
        DELETE = 'delete', 'Delete'
        ACTIVATE = 'activate', 'Activate'
        DEACTIVATE = 'deactivate', 'Deactivate'
        RESET_PASSWORD = 'reset_password', 'Reset password'
        CHANGE_PASSWORD = 'change_password', 'Change password'
        CHANGE_LANGUAGE = 'change_language', 'Change language'
        ACCESS_KEY_ISSUED = 'access_key_issued', 'Access key issued'
        ACCESS_KEY_REDEEMED = 'access_key_redeemed', 'Access key redeemed'
        ACCESS_KEY_REVOKED = 'access_key_revoked', 'Access key revoked'

    company = models.ForeignKey(
        'companies.Company',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='audit_logs',
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
    )
    actor_username = models.CharField(max_length=150, blank=True)
    actor_role = models.CharField(max_length=20, blank=True)
    action = models.CharField(max_length=50, choices=Action.choices, db_index=True)
    object_type = models.CharField(max_length=100, db_index=True)
    object_id = models.CharField(max_length=64, blank=True, db_index=True)
    object_repr = models.CharField(max_length=255, blank=True)
    changes = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Audit log'
        verbose_name_plural = 'Audit logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['action', 'created_at']),
            models.Index(fields=['object_type', 'object_id']),
            models.Index(fields=['actor_role', 'created_at']),
        ]

    def __str__(self):
        """
        Строковое представление записи аудита.

        Возвращает описание действия в формате: "actor action target".
        """
        actor = self.actor_username or 'system'
        target = self.object_repr or self.object_type
        return f'{actor} {self.action} {target}'
