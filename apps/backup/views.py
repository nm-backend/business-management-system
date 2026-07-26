"""
API views for backup management.

ТОЛЬКО супер-администратор платформы: pg_dump выгружает базу ЦЕЛИКОМ (данные
всех компаний), поэтому доступ владельца компании означал бы утечку данных
других арендаторов в его S3/Telegram. Конфигурация одна на платформу
(company=None).
"""
import json

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from django_celery_beat.models import PeriodicTask, IntervalSchedule

from apps.core.permissions import IsSuperAdmin
from .models import BackupConfig, BackupLog
from .tasks import run_backup_task


class BackupConfigView(APIView):
    """
    GET/PATCH /api/v1/backup/config/ — настройки backup для компании.

    GET — возвращает текущую конфигурацию (или дефолтную, если ещё не создана)
    PATCH — обновляет настройки
    """
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        config, _ = BackupConfig.objects.get_or_create(company=None)
        return Response({
            'is_enabled': config.is_enabled,
            'schedule': config.schedule,
            'storage': config.storage,
            'keep_last': config.keep_last,
            's3_endpoint': config.s3_endpoint,
            's3_region': config.s3_region,
            's3_bucket': config.s3_bucket,
            's3_path_prefix': config.s3_path_prefix,
            'telegram_chat_id': config.telegram_chat_id,
            'has_s3_key': bool(config.s3_access_key),
            'has_telegram_token': bool(config.telegram_bot_token),
        })

    def patch(self, request):
        config, _ = BackupConfig.objects.get_or_create(company=None)
        allowed_fields = [
            'is_enabled', 'schedule', 'storage', 'keep_last',
            's3_endpoint', 's3_region', 's3_bucket', 's3_path_prefix',
            'telegram_chat_id',
        ]
        # S3 ключи обновляем только если переданы явно (не пустые)
        if 's3_access_key' in request.data and request.data['s3_access_key']:
            allowed_fields.append('s3_access_key')
        if 's3_secret_key' in request.data and request.data['s3_secret_key']:
            allowed_fields.append('s3_secret_key')
        if 'telegram_bot_token' in request.data and request.data['telegram_bot_token']:
            allowed_fields.append('telegram_bot_token')

        for field in allowed_fields:
            if field in request.data:
                setattr(config, field, request.data[field])

        config.save(update_fields=allowed_fields + ['updated_at'])

        # Синхронизируем с Celery Beat
        self._sync_beat_schedule(config)

        return Response({'status': 'ok', 'is_enabled': config.is_enabled})

    def _sync_beat_schedule(self, config):
        """Создаёт/обновляет/удаляет PeriodicTask в Celery Beat."""
        task_name = 'backup-platform'
        if not config.is_enabled:
            PeriodicTask.objects.filter(name=task_name).delete()
            return

        schedule_map = {
            'daily': IntervalSchedule.MINUTES,
            'weekly': IntervalSchedule.DAYS,
            'monthly': IntervalSchedule.DAYS,
        }
        every_map = {'daily': 1440, 'weekly': 7, 'monthly': 30}
        period = schedule_map.get(config.schedule, IntervalSchedule.MINUTES)
        every = every_map.get(config.schedule, 1440)

        schedule, _ = IntervalSchedule.objects.get_or_create(
            every=every,
            period=period,
        )

        PeriodicTask.objects.update_or_create(
            name=task_name,
            defaults={
                'task': 'apps.backup.tasks.run_backup_task',
                'interval': schedule,
                # json.dumps, а не f-string: при company_id=None f-string давал
                # '[None, null]' — невалидный JSON, и beat не смог бы запустить задачу.
                'args': json.dumps([config.company_id, None]),
                'enabled': True,
            },
        )


class BackupTriggerView(APIView):
    """
    POST /api/v1/backup/trigger/ — ручной запуск backup.
    """
    permission_classes = [IsSuperAdmin]

    def post(self, request):
        config, _ = BackupConfig.objects.get_or_create(company=None)
        if not config.is_enabled:
            return Response({'error': 'Backup is not enabled'}, status=status.HTTP_400_BAD_REQUEST)

        # Запускаем Celery задачу асинхронно
        run_backup_task.delay(
            company_id=None,          # платформенный бэкап: дамп всей БД
            user_id=request.user.id,
        )
        return Response({'status': 'started', 'message': 'Backup запущен'})


class BackupLogsView(APIView):
    """
    GET /api/v1/backup/logs/ — история backup'ов.
    """
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        logs = BackupLog.objects.filter(company=None)[:20]
        return Response([{
            'id': log.id,
            'status': log.status,
            'file_name': log.file_name,
            'file_size': log.file_size,
            'storage': log.storage,
            'error_message': log.error_message,
            'duration_seconds': log.duration_seconds,
            'created_at': log.created_at.isoformat() if log.created_at else None,
        } for log in logs])
