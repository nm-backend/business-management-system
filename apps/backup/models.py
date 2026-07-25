"""
Backup models - конфигурация и логи резервного копирования.

Позволяет владельцу настроить автоматический backup БД:
- В S3 (AWS S3 / MinIO / any S3-compatible)
- В Telegram (через Bot API)
- По расписанию Celery Beat
"""
from django.db import models
from apps.core.models import TimestampedModel


class BackupConfig(TimestampedModel):
    """
    Настройки автоматического резервного копирования.

    Создаётся автоматически для каждой компании при первом обращении.
    Доступна только владельцу компании.
    """
    class Schedule(models.TextChoices):
        DAILY = 'daily', 'Ежедневно'
        WEEKLY = 'weekly', 'Еженедельно'
        MONTHLY = 'monthly', 'Ежемесячно'

    class Storage(models.TextChoices):
        S3 = 's3', 'S3 (AWS / MinIO)'
        TELEGRAM = 'telegram', 'Telegram'
        BOTH = 'both', 'S3 + Telegram'

    company = models.ForeignKey(
        'companies.Company', on_delete=models.CASCADE, related_name='backup_configs',
        verbose_name='Компания',
    )
    is_enabled = models.BooleanField('Авто-бэкап включён', default=False)
    schedule = models.CharField(
        'Расписание', max_length=10, choices=Schedule.choices, default=Schedule.DAILY,
    )
    storage = models.CharField(
        'Хранилище', max_length=10, choices=Storage.choices, default=Storage.S3,
    )
    keep_last = models.PositiveIntegerField('Хранить последних', default=7, help_text='Количество последних бэкапов')

    # S3 настройки
    s3_endpoint = models.CharField('S3 Endpoint', max_length=255, blank=True, default='')
    s3_region = models.CharField('S3 Region', max_length=100, blank=True, default='')
    s3_bucket = models.CharField('S3 Bucket', max_length=255, blank=True, default='skladpro-backups')
    s3_access_key = models.CharField('S3 Access Key', max_length=255, blank=True, default='')
    s3_secret_key = models.CharField('S3 Secret Key', max_length=255, blank=True, default='')
    s3_path_prefix = models.CharField('S3 Path Prefix', max_length=255, blank=True, default='backups/')

    # Telegram настройки
    telegram_bot_token = models.CharField('Telegram Bot Token', max_length=255, blank=True, default='')
    telegram_chat_id = models.CharField('Telegram Chat ID', max_length=100, blank=True, default='')

    class Meta:
        verbose_name = 'Настройка бэкапа'
        verbose_name_plural = 'Настройки бэкапа'
        # Одна настройка на компанию
        constraints = [
            models.UniqueConstraint(fields=['company'], name='backup_single_config_per_company'),
        ]

    def __str__(self):
        return f'Backup config for company {self.company_id}'


class BackupLog(TimestampedModel):
    """
    Лог выполнения резервного копирования.

    Создаётся каждый раз при запуске backup (ручном или по расписанию).
    """
    class Status(models.TextChoices):
        RUNNING = 'running', 'Выполняется'
        SUCCESS = 'success', 'Успешно'
        FAILED = 'failed', 'Ошибка'

    company = models.ForeignKey(
        'companies.Company', on_delete=models.CASCADE, related_name='backup_logs',
        verbose_name='Компания',
    )
    status = models.CharField('Статус', max_length=10, choices=Status.choices, default=Status.RUNNING)
    file_name = models.CharField('Имя файла', max_length=255, blank=True)
    file_size = models.BigIntegerField('Размер (байт)', null=True, blank=True)
    storage = models.CharField('Хранилище', max_length=20, blank=True)
    s3_key = models.CharField('S3 Key', max_length=500, blank=True)
    telegram_message_id = models.CharField('Telegram Message ID', max_length=100, blank=True)
    error_message = models.TextField('Ошибка', blank=True)
    duration_seconds = models.FloatField('Длительность (сек)', null=True, blank=True)
    triggered_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='triggered_backups', verbose_name='Запущен пользователем',
    )

    class Meta:
        verbose_name = 'Лог бэкапа'
        verbose_name_plural = 'Логи бэкапов'
        ordering = ['-created_at']

    def __str__(self):
        return f'Backup {self.file_name} - {self.status} ({self.created_at})'
