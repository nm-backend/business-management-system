from django.apps import AppConfig


class BillingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.billing'
    verbose_name = 'Подписки (SaaS billing)'

    def ready(self):
        from . import signals  # noqa: F401  (регистрирует post_save на Company)
        # Celery-задачи подхватываются autodiscover_tasks() в skladpro.celery.
