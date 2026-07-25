"""
Celery configuration for SkladPro.

Запуск воркера:
  celery -A skladpro worker -l info

Запуск Beat-планировщика:
  celery -A skladpro beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler

Оба вместе (dev):
  celery -A skladpro worker -B -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
"""
import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'skladpro.settings')

app = Celery('skladpro')

# Используем настройки Django с префиксом CELERY
app.config_from_object('django.conf:settings', namespace='CELERY')

# Авто-обнаружение задач в приложениях
app.autodiscover_tasks()

@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
