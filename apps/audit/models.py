from django.conf import settings
from django.db import models
from apps.core.models import TimestampedModel


class AuditLog(TimestampedModel):
    """
    Журнал действий нужен для требований безопасности из ТЗ.

    Мы храним не только факт изменения, но и контекст: кто сделал действие,
    над какой сущностью, с какого IP и какие важные поля изменились. Это
    помогает владельцу бизнеса восстановить историю операций без доступа к
    низкоуровневым логам сервера.
    """

    class Action(models.TextChoices):
        SETUP_OWNER = 'setup_owner', 'Setup owner'
        LOGIN = 'login', 'Login'
        LOGOUT = 'logout', 'Logout'
        CREATE = 'create', 'Create'
        UPDATE = 'update', 'Update'
        ARCHIVE = 'archive', 'Archive'
        ACTIVATE = 'activate', 'Activate'
        DEACTIVATE = 'deactivate', 'Deactivate'
        RESET_PASSWORD = 'reset_password', 'Reset password'
        CHANGE_PASSWORD = 'change_password', 'Change password'
        CHANGE_LANGUAGE = 'change_language', 'Change language'

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
        actor = self.actor_username or 'system'
        target = self.object_repr or self.object_type
        return f'{actor} {self.action} {target}'
