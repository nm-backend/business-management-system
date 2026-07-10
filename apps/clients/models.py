"""
Clients models - управление клиентами.

Этот модуль содержит модель для управления клиентами, их заказами,
финансовыми данными и архивацией.

ВАЖНО: Финансовые поля доступны только владельцу (owner).
"""
from django.db import models
from apps.core.models import TimestampedModel, SoftDeleteModel


class Client(TimestampedModel, SoftDeleteModel):
    """
    Модель клиента.

    Хранит информацию о клиентах, их заказах и финансовых данных.
    Поддерживает архивацию завершенных клиентов.

    Поля:
        name: CharField - имя клиента
        phone: CharField - телефон
        address: TextField - адрес
        total_orders_amount: DecimalField - общая сумма заказов (ФИНАНСОВОЕ ПОЛЕ)
        total_paid: DecimalField - всего оплачено (ФИНАНСОВОЕ ПОЛЕ)
        debt: DecimalField - долг клиента (ФИНАНСОВОЕ ПОЛЕ)
        profit: DecimalField - прибыль от клиента (ФИНАНСОВОЕ ПОЛЕ)
        is_active: BooleanField - активен ли клиент
        is_archived: BooleanField - архивирован ли клиент
        notes: TextField - заметки

    Свойства:
        has_debt: bool - True если есть долг
        has_active_orders: bool - True если есть активные заказы

    Особенности:
        - Поддерживает мягкое удаление (SoftDeleteModel)
        - Автоматические временные метки (TimestampedModel)
        - Архивация при завершении всех заказов и оплате
    """
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=20, blank=True, default='')
    address = models.TextField(blank=True, default='')
    total_orders_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)  # ФИНАНСОВОЕ ПОЛЕ
    total_paid = models.DecimalField(max_digits=15, decimal_places=2, default=0)  # ФИНАНСОВОЕ ПОЛЕ
    debt = models.DecimalField(max_digits=15, decimal_places=2, default=0)  # ФИНАНСОВОЕ ПОЛЕ
    profit = models.DecimalField(max_digits=15, decimal_places=2, default=0)  # ФИНАНСОВОЕ ПОЛЕ
    is_active = models.BooleanField(default=True)
    is_archived = models.BooleanField(default=False)
    notes = models.TextField(blank=True, default='')

    class Meta:
        verbose_name = 'Client'
        verbose_name_plural = 'Clients'
        ordering = ['-created_at']

    def __str__(self):
        """
        Строковое представление клиента.

        Возвращает имя клиента с телефоном если указан.
        """
        return f"{self.name} ({self.phone})" if self.phone else self.name

    @property
    def has_debt(self):
        """
        Проверяет, есть ли у клиента долг.

        Возвращает:
            bool - True если debt > 0
        """
        return self.debt > 0

    @property
    def has_active_orders(self):
        """
        Проверяет, есть ли у клиента активные заказы.

        Возвращает:
            bool - True если есть не завершенные заказы
        """
        return self.orders.filter(status__in=['new', 'in_progress', 'awaiting_confirmation']).exists()
