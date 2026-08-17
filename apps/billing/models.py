"""
Подписки компаний (SaaS billing).

Модели жизненного цикла подписки:

    Subscription   — одна подписка на компанию (OneToOne). Статусы:
                     active → expired → frozen → active (после продления).
                     Заморозка НЕ трогает Company.is_active и is_active
                     пользователей: вход, профиль и статус подписки остаются
                     доступными (whitelist в apps.billing.gate), а бизнес-
                     функции блокируются единым subscription gate.
    SubscriptionEvent — история изменений подписки (кто, что, когда).
    Invoice        — счёт на оплату. Создаётся при продлении через
                     payment adapter (apps.billing.payments); сейчас
                     провайдер по умолчанию manual — оплату подтверждает
                     супер-администратор, позже подключаются Payme/Click
                     без переделки основной логики.

Почему заморозка на уровне подписки, а не Company.is_active:
блокировка компании (toggle_active) каскадно гасит is_active у всех
пользователей и блэклистит токены — вход становится невозможен. По ТЗ
замороженная компания обязана пускать на вход, профиль, статус подписки
и оплату, поэтому freeze — это исключительно статус подписки.
"""
from datetime import timedelta
from math import ceil

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import TimestampedModel


class Subscription(TimestampedModel):
    """Подписка компании на SaaS-тариф."""

    class Plan(models.TextChoices):
        FREE = 'free', 'Free'
        PRO = 'pro', 'Pro'

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        EXPIRED = 'expired', 'Expired'
        FROZEN = 'frozen', 'Frozen'

    company = models.OneToOneField(
        'companies.Company', on_delete=models.CASCADE, related_name='subscription',
        verbose_name='Компания',
    )
    plan = models.CharField(max_length=10, choices=Plan.choices, default=Plan.FREE,
                            verbose_name='Тариф')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE,
                              db_index=True, verbose_name='Статус')
    started_at = models.DateTimeField(verbose_name='Начало периода')
    expires_at = models.DateTimeField(db_index=True, verbose_name='Действует до')
    last_renewed_at = models.DateTimeField(null=True, blank=True, verbose_name='Последнее продление')
    frozen_at = models.DateTimeField(null=True, blank=True, verbose_name='Заморожена')
    # Когда последний раз отправляли предупреждение об окончании (раз в день).
    last_reminder_at = models.DateTimeField(null=True, blank=True, verbose_name='Напоминание отправлено')

    class Meta:
        verbose_name = 'Подписка'
        verbose_name_plural = 'Подписки'
        ordering = ['-expires_at']

    def __str__(self):
        return f'{self.company_id} · {self.plan} · {self.status} до {self.expires_at:%d.%m.%Y}'

    @property
    def is_blocked(self):
        """
        Эффективно заморожена ли компания прямо сейчас.

        Покрывает и формальный статус (expired/frozen), и «серую зону» между
        истечением срока и прогоном Celery-задачи: подписка ещё active, но
        expires_at уже прошёл — бизнес-функции должны быть заблокированы,
        иначе компания получает бесплатный «хвост» после окончания.
        """
        return self.status != self.Status.ACTIVE or timezone.now() >= self.expires_at

    @property
    def days_left(self):
        """Полных дней до окончания (0 — уже истекла)."""
        delta = self.expires_at - timezone.now()
        return max(0, ceil(delta.total_seconds() / 86400))


class SubscriptionEvent(models.Model):
    """
    История изменений подписки.

    Каждая смена статуса/срока — отдельная строка: кто (или system/Celery),
    из какого статуса в какой, старые/новые сроки. Owner видит историю своей
    компании через API, супер-админ — в админке и API.
    """

    class Action(models.TextChoices):
        CREATED = 'created', 'Создана'
        ACTIVATED = 'activated', 'Активирована'
        RENEWED = 'renewed', 'Продлена'
        EXTENDED = 'extended', 'Продлена супер-админом'
        EXPIRED = 'expired', 'Истекла'
        FROZEN = 'frozen', 'Заморожена'
        UNFROZEN = 'unfrozen', 'Разморожена'
        PLAN_CHANGED = 'plan_changed', 'Тариф изменён'
        INVOICE_PAID = 'invoice_paid', 'Счёт оплачен'

    subscription = models.ForeignKey(
        Subscription, on_delete=models.CASCADE, related_name='events', verbose_name='Подписка',
    )
    company = models.ForeignKey(
        'companies.Company', on_delete=models.CASCADE, related_name='subscription_events',
        verbose_name='Компания',
    )
    action = models.CharField(max_length=20, choices=Action.choices, verbose_name='Действие')
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name='Кто выполнил',
    )
    actor_role = models.CharField(max_length=20, blank=True, verbose_name='Роль исполнителя')
    from_status = models.CharField(max_length=10, blank=True, verbose_name='Было')
    to_status = models.CharField(max_length=10, blank=True, verbose_name='Стало')
    old_expires_at = models.DateTimeField(null=True, blank=True, verbose_name='Было до')
    new_expires_at = models.DateTimeField(null=True, blank=True, verbose_name='Стало до')
    note = models.TextField(blank=True, default='', verbose_name='Комментарий')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Когда')

    class Meta:
        verbose_name = 'Событие подписки'
        verbose_name_plural = 'История подписок'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['subscription', 'created_at']),
            models.Index(fields=['company', 'created_at']),
        ]

    def __str__(self):
        actor = self.actor_role or 'system'
        return f'{actor} {self.action} sub #{self.subscription_id}'


class Invoice(TimestampedModel):
    """
    Счёт на оплату подписки.

    Создаётся при продлении (owner) и проходит через payment adapter.
    Статусы: pending → paid (подписка продлевается) / failed / cancelled.
    provider — ключ адаптера ('manual' сейчас; позже 'payme'/'click').
    """

    class Status(models.TextChoices):
        PENDING = 'pending', 'Ожидает оплаты'
        PAID = 'paid', 'Оплачен'
        FAILED = 'failed', 'Ошибка'
        CANCELLED = 'cancelled', 'Отменён'

    company = models.ForeignKey(
        'companies.Company', on_delete=models.CASCADE, related_name='invoices',
        verbose_name='Компания',
    )
    subscription = models.ForeignKey(
        Subscription, on_delete=models.CASCADE, related_name='invoices', verbose_name='Подписка',
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Сумма')
    currency = models.CharField(max_length=3, default='UZS', verbose_name='Валюта')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING,
                              db_index=True, verbose_name='Статус')
    provider = models.CharField(max_length=20, default='manual', verbose_name='Платёжный провайдер')
    provider_payment_id = models.CharField(max_length=128, blank=True, default='',
                                           verbose_name='ID платежа провайдера')
    metadata = models.JSONField(default=dict, blank=True, verbose_name='Дополнительные данные')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name='Кем создан',
    )
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name='Оплачен когда')

    class Meta:
        verbose_name = 'Счёт'
        verbose_name_plural = 'Счета'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['subscription', 'status']),
            models.Index(fields=['company', 'status']),
        ]

    def __str__(self):
        return f'Invoice #{self.pk} ({self.status}) {self.amount} {self.currency}'
