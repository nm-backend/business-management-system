from django.apps import AppConfig


class ClientsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.clients'
    verbose_name = 'Clients'

    def ready(self):
        """Подключает сигналы при готовности приложения.
        Импорт модуля регистрирует @receiver декораторы."""
        from . import signals  # noqa: F401 — activates @receiver decorators
