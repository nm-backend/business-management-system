"""
Company model - арендатор (tenant) в мультикомпанийной архитектуре.

Каждая компания полностью изолирована: пользователи, склад, заказы, клиенты,
финансы и все прочие данные привязаны к company. Пользователь одной компании
никогда не видит данные другой (изоляция обеспечивается на уровне queryset
в CompanyScopedViewSet и проверяется в тестах изоляции).

Компании создаёт платформенный супер-администратор (role='superadmin').
"""
from django.db import models

from apps.core.models import TimestampedModel


class Company(TimestampedModel):
    name = models.CharField(max_length=255, unique=True, verbose_name='Название')
    is_active = models.BooleanField(default=True, db_index=True, verbose_name='Активен')

    class Meta:
        verbose_name = 'Компания'
        verbose_name_plural = 'Компании'
        ordering = ['name']

    def __str__(self):
        return self.name
