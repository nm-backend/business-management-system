"""
Celery tasks for automated database backup.

Поддерживает выгрузку в S3 и/или Telegram.
Запускается по расписанию Celery Beat.
"""
import io
import json
import logging
import os
import subprocess
import tarfile
import tempfile
import time
from datetime import datetime
from pathlib import Path

from celery import shared_task
from django.conf import settings
from django.utils import timezone as tz

logger = logging.getLogger(__name__)


def _run_dump(db_config):
    """Создаёт дамп PostgreSQL через pg_dump и возвращает путь к файлу."""
    host = db_config.get('HOST', 'localhost')
    port = db_config.get('PORT', 5432)
    name = db_config.get('NAME', '')
    user = db_config.get('USER', '')
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'skladpro_backup_{timestamp}.sql.gz'

    tmpdir = tempfile.mkdtemp()
    filepath = Path(tmpdir) / filename

    env = os.environ.copy()
    password = db_config.get('PASSWORD', '')
    if password:
        env['PGPASSWORD'] = password

    cmd = [
        'pg_dump',
        f'--host={host}',
        f'--port={port}',
        f'--username={user}',
        '--no-owner',
        '--no-acl',
        '--compress=9',  # gzip
        name,
    ]

    try:
        with open(filepath, 'wb') as f:
            result = subprocess.run(
                cmd, env=env, stdout=f, stderr=subprocess.PIPE,
                timeout=300,  # 5 min max
            )
        if result.returncode != 0:
            error = result.stderr.decode('utf-8', errors='replace')
            raise RuntimeError(f'pg_dump failed: {error}')
        return str(filepath), filename
    except FileNotFoundError:
        raise RuntimeError('pg_dump not found. Install PostgreSQL client tools.')
    except subprocess.TimeoutExpired:
        raise RuntimeError('pg_dump timed out after 5 minutes.')


def _bundle_backup(filepath, filename, media_root=None):
    """
    Собирает единый tar.gz: дамп БД + media-файлы (фото заказов и т.п.).

    Раньше бэкапилась только БД: медиа лежали только на диске сервера, и после
    падения/переезда фото заказов терялись безвозвратно. Внутри архива:
    dump.sql.gz и media/ (если папка существует и не пуста).
    """
    bundle = Path(filepath).with_suffix('.tar.gz')
    bundle_name = bundle.name

    with tarfile.open(bundle, 'w:gz') as tar:
        tar.add(filepath, arcname='dump.sql.gz')
        if media_root and Path(media_root).exists():
            media_dir = Path(media_root)
            if any(media_dir.iterdir()):
                tar.add(media_root, arcname='media', recursive=True)

    return str(bundle), bundle_name


def _upload_to_s3(filepath, filename, config):
    """Загружает файл в S3."""
    import boto3
    from botocore.exceptions import ClientError

    endpoint = config.s3_endpoint or None
    s3 = boto3.client(
        's3',
        endpoint_url=endpoint,
        region_name=config.s3_region or 'us-east-1',
        aws_access_key_id=config.s3_access_key,
        aws_secret_access_key=config.s3_secret_key,
    )

    key = f'{config.s3_path_prefix.rstrip("/")}/{filename}'
    try:
        with open(filepath, 'rb') as f:
            s3.upload_fileobj(f, config.s3_bucket, key)
        return key
    except ClientError as e:
        raise RuntimeError(f'S3 upload failed: {e}')


def _send_to_telegram(filepath, filename, config, company_name):
    """Отправляет файл в Telegram чат."""
    import requests

    url = f'https://api.telegram.org/bot{config.telegram_bot_token}/sendDocument'
    with open(filepath, 'rb') as f:
        response = requests.post(
            url,
            data={
                'chat_id': config.telegram_chat_id,
                'caption': f'📦 Backup: {company_name}\n📁 {filename}',
            },
            files={'document': f},
            timeout=120,
        )
    data = response.json()
    if not data.get('ok'):
        raise RuntimeError(f'Telegram send failed: {data.get("description", "unknown")}')
    return str(data['result']['message_id'])


def _redact_secrets(message, config):
    """
    Вырезает секреты из текста ошибки перед сохранением в БД.

    error_message отдаётся через API (/api/v1/backup/logs/), а исключения
    requests/boto3 могут содержать токен бота или ключи S3.
    """
    for secret in (
        getattr(config, 'telegram_bot_token', ''),
        getattr(config, 's3_secret_key', ''),
        getattr(config, 's3_access_key', ''),
    ):
        if secret:
            message = message.replace(secret, '***')
    return message


def _backup_error_action(self, exc):
    """
    Готовит сообщение об ошибке и решает, нужен ли автоповтор.

    Возвращает (error_message, should_retry). Вынесено из задачи отдельной
    функцией, чтобы ретрай-логику можно было тестировать без брокера Celery.
    """
    retries = getattr(self.request, 'retries', 0) if self.request else 0
    message = str(exc)
    should_retry = retries < self.max_retries
    if should_retry:
        message = f'{message} | retry #{retries + 1} через {self.default_retry_delay}s'
    return message, should_retry


def _cleanup_old_backups(config):
    """Удаляет старые backup-файлы (keep_last = 7 по умолчанию)."""
    from .models import BackupLog

    logs = BackupLog.objects.filter(
        company=config.company,
        status=BackupLog.Status.SUCCESS,
    ).order_by('-created_at')

    # Оставляем последние keep_last
    keep = config.keep_last or 7
    to_delete = list(logs[keep:])

    for log in to_delete:
        # Пытаемся удалить из S3
        if log.s3_key and config.storage in ('s3', 'both'):
            try:
                import boto3
                s3 = boto3.client(
                    's3',
                    endpoint_url=config.s3_endpoint or None,
                    region_name=config.s3_region or 'us-east-1',
                    aws_access_key_id=config.s3_access_key,
                    aws_secret_access_key=config.s3_secret_key,
                )
                s3.delete_object(Bucket=config.s3_bucket, Key=log.s3_key)
            except Exception:
                pass
        log.delete()


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def run_backup_task(self, company_id, user_id=None):
    """
    Celery-задача: создаёт дамп БД и выгружает в настроенное хранилище.

    Args:
        company_id: int — ID компании
        user_id: int или None — ID пользователя, запустившего backup (для ручного запуска)
    """
    from apps.accounts.models import User
    from .models import BackupConfig, BackupLog

    try:
        config = BackupConfig.objects.get(company_id=company_id, is_enabled=True)
    except BackupConfig.DoesNotExist:
        logger.info(f'Backup not enabled for company {company_id}, skipping')
        return

    log = BackupLog.objects.create(
        company_id=company_id,
        status=BackupLog.Status.RUNNING,
        triggered_by_id=user_id,
    )

    start_time = time.time()
    filepath = None
    filename = ''
    company_name = config.company.name if config.company else ''

    try:
        # 1. Создать дамп и собрать бандл с media-файлами.
        filepath, filename = _run_dump(settings.DATABASES['default'])
        filepath, filename = _bundle_backup(filepath, filename, settings.MEDIA_ROOT)
        file_size = os.path.getsize(filepath)
        log.file_name = filename
        log.file_size = file_size

        # 2. Загрузить в S3
        if config.storage in ('s3', 'both') and config.s3_access_key:
            s3_key = _upload_to_s3(filepath, filename, config)
            log.s3_key = s3_key
            log.storage = 's3'

        # 3. Отправить в Telegram
        if config.storage in ('telegram', 'both') and config.telegram_bot_token:
            msg_id = _send_to_telegram(filepath, filename, config, company_name)
            log.telegram_message_id = msg_id
            log.storage = 'telegram' if log.storage == '' else 'both'

        log.status = BackupLog.Status.SUCCESS

    except Exception as e:
        logger.error(f'Backup failed for company {company_id}: {e}')
        log.status = BackupLog.Status.FAILED
        # Сообщения об ошибках сохраняются в БД и отдаются через API. Ошибки
        # requests включают полный URL, а он содержит токен Telegram-бота
        # (https://api.telegram.org/bot<TOKEN>/...) — вырезаем его.
        message, should_retry = _backup_error_action(self, e)
        log.error_message = _redact_secrets(message, config)
        # Автоповтор транзиентных сбоев (S3/Telegram/сеть): без self.retry()
        # max_retries был мёртвой конфигурацией, и задача падала с первого раза.
        if should_retry:
            raise self.retry(exc=e, countdown=self.default_retry_delay)

    finally:
        log.duration_seconds = round(time.time() - start_time, 1)
        log.save(update_fields=[
            'status', 'file_name', 'file_size', 's3_key',
            'telegram_message_id', 'error_message', 'duration_seconds', 'storage',
        ])
        # Очистить временный файл
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
                os.rmdir(os.path.dirname(filepath))
            except Exception:
                pass

    # 4. Удалить старые бэкапы
    if log.status == BackupLog.Status.SUCCESS:
        try:
            _cleanup_old_backups(config)
        except Exception as e:
            logger.warning(f'Old backup cleanup failed: {e}')

    return log.status
