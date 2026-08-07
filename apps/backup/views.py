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
        # Валидация ДО записи: сырые значения из PATCH раньше доходили до БД —
        # keep_last='abc' ронял сохранение в 500, а schedule='hourly' молча
        # сохранялся и в _sync_beat_schedule превращался в ЕЖЕЧАСНЫЙ бэкап
        # (маппинг по умолчанию MINUTES/1440).
        updates = {}
        for field in [
            'is_enabled', 'schedule', 'storage', 'keep_last',
            's3_endpoint', 's3_region', 's3_bucket', 's3_path_prefix',
            'telegram_chat_id',
        ]:
            if field not in request.data:
                continue
            value = request.data[field]
            if field == 'schedule' and value not in BackupConfig.Schedule.values:
                return Response({'error': f'Invalid schedule: {value!r}'}, status=status.HTTP_400_BAD_REQUEST)
            if field == 'storage' and value not in BackupConfig.Storage.values:
                return Response({'error': f'Invalid storage: {value!r}'}, status=status.HTTP_400_BAD_REQUEST)
            if field == 'keep_last':
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    return Response({'error': 'keep_last must be an integer'}, status=status.HTTP_400_BAD_REQUEST)
                if not 1 <= value <= 365:
                    return Response({'error': 'keep_last must be between 1 and 365'}, status=status.HTTP_400_BAD_REQUEST)
            if field == 'is_enabled' and value not in (True, False):
                return Response({'error': 'is_enabled must be a boolean'}, status=status.HTTP_400_BAD_REQUEST)
            updates[field] = value

        # Секреты обновляем только если переданы явно (не пустые).
        for field in ('s3_access_key', 's3_secret_key', 'telegram_bot_token'):
            value = request.data.get(field)
            if value:
                updates[field] = value

        if updates:
            for field, value in updates.items():
                setattr(config, field, value)
            config.save(update_fields=list(updates) + ['updated_at'])

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
