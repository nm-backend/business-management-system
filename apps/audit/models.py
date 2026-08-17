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
        SUBSCRIPTION_*: управление подпиской компании (SaaS)
        """
        SETUP_OWNER = 'setup_owner', 'Создание супер-админа'
        LOGIN = 'login', 'Вход'
        LOGOUT = 'logout', 'Выход'
        CREATE = 'create', 'Создание'
        UPDATE = 'update', 'Изменение'
        ARCHIVE = 'archive', 'Архивация'
        DELETE = 'delete', 'Удаление'
        ACTIVATE = 'activate', 'Разблокировка'
        DEACTIVATE = 'deactivate', 'Блокировка'
        RESET_PASSWORD = 'reset_password', 'Сброс пароля'
        CHANGE_PASSWORD = 'change_password', 'Смена пароля'
        CHANGE_LANGUAGE = 'change_language', 'Смена языка'
        ACCESS_KEY_ISSUED = 'access_key_issued', 'Код доступа выдан'
        ACCESS_KEY_REDEEMED = 'access_key_redeemed', 'Код доступа активирован'
        ACCESS_KEY_REVOKED = 'access_key_revoked', 'Код доступа отозван'
        TWO_FACTOR_ENABLED = 'two_factor_enabled', 'Двухэтапное подтверждение включено'
        TWO_FACTOR_DISABLED = 'two_factor_disabled', 'Двухэтапное подтверждение выключено'
        TWO_FACTOR_FAILED = 'two_factor_failed', 'Неверный код подтверждения'
        TWO_FACTOR_RECOVERY_USED = 'two_factor_recovery_used', 'Использован резервный код'
        TWO_FACTOR_RECOVERY_REGENERATED = (
            'two_factor_recovery_regenerated', 'Резервные коды перевыпущены',
        )
        TOKEN_THEFT_DETECTED = 'token_theft_detected', 'Обнаружена кража токена'
        SUBSCRIPTION_ACTIVATED = 'subscription_activated', 'Подписка активирована'
        SUBSCRIPTION_RENEWED = 'subscription_renewed', 'Подписка продлена'
        SUBSCRIPTION_EXTENDED = 'subscription_extended', 'Подписка продлена супер-админом'
        SUBSCRIPTION_END_SET = 'subscription_end_set', 'Срок подписки изменён'
        SUBSCRIPTION_GRACE_STARTED = 'subscription_grace_started', 'Льготный период начался'
        SUBSCRIPTION_FROZEN = 'subscription_frozen', 'Компания заморожена'
        SUBSCRIPTION_UNFROZEN = 'subscription_unfrozen', 'Компания разморожена'
        SUBSCRIPTION_EXPIRED = 'subscription_expired', 'Подписка истекла'
        SUBSCRIPTION_PLAN_CHANGED = 'subscription_plan_changed', 'Тариф изменён'
        SUBSCRIPTION_RENEWAL_REQUESTED = 'subscription_renewal_requested', 'Запрошено продление подписки'
        INVOICE_PAID = 'invoice_paid', 'Счёт оплачен'

    company = models.ForeignKey(
        'companies.Company',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='audit_logs', verbose_name='Компания'
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs', verbose_name='Кто выполнил'
    )
    actor_username = models.CharField(max_length=150, blank=True, verbose_name='Логин исполнителя')
    actor_role = models.CharField(max_length=20, blank=True, verbose_name='Роль исполнителя')
    action = models.CharField(max_length=50, choices=Action.choices, db_index=True, verbose_name='Действие')
    object_type = models.CharField(max_length=100, db_index=True, verbose_name='Тип объекта')
    object_id = models.CharField(max_length=64, blank=True, db_index=True, verbose_name='ID объекта')
    object_repr = models.CharField(max_length=255, blank=True, verbose_name='Объект')
    changes = models.JSONField(default=dict, blank=True, verbose_name='Изменения')
    metadata = models.JSONField(default=dict, blank=True, verbose_name='Дополнительные данные')
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name='IP-адрес')
    user_agent = models.TextField(blank=True, verbose_name='Устройство')

    class Meta:
        verbose_name = 'Запись журнала'
        verbose_name_plural = 'Журнал действий'
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
