"""
Messaging models - управление сообщениями и уведомлениями.

Этот модуль содержит модели для внутреннего чата между пользователями
и системы уведомлений о важных событиях.
"""
from django.db import models
from apps.core.models import TimestampedModel


class Message(TimestampedModel):
    """
    Модель сообщения во внутреннем чате.

    Хранит сообщения между пользователями системы.
    Поддерживает личные сообщения и групповые рассылки.

    Поля:
        sender: ForeignKey - отправитель
        recipient: ForeignKey - получатель (null для групповых сообщений)
        subject: CharField - тема сообщения
        content: TextField - содержание
        is_read: BooleanField - прочитано ли
        is_group: BooleanField - групповое ли сообщение
        read_at: DateTimeField - когда прочитано

    Свойства:
        is_unread: bool - True если не прочитано

    Особенности:
        - Автоматические временные метки (TimestampedModel)
        - Отслеживание прочтения
        - Личные и групповые сообщения
    """
    company = models.ForeignKey('companies.Company', on_delete=models.CASCADE, related_name='messages', null=True)
    sender = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='sent_messages')
    recipient = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='received_messages', null=True, blank=True)
    subject = models.CharField(max_length=255, blank=True, default='')
    content = models.TextField()
    is_read = models.BooleanField(default=False)
    is_group = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        """
        Метаданные модели Message.

        Атрибуты:
            verbose_name: человекочитаемое имя модели
            verbose_name_plural: множественное число
            ordering: сортировка по убыванию даты создания
            indexes: индексы для оптимизации запросов
        """
        verbose_name = 'Message'
        verbose_name_plural = 'Messages'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['sender', 'created_at']),
            models.Index(fields=['recipient', 'is_read']),
        ]

    def __str__(self):
        """
        Строковое представление сообщения.

        Возвращает отправителя и тему.
        """
        return f"{self.sender.username} - {self.subject or 'No subject'}"

    @property
    def is_unread(self):
        """
        Проверяет, не прочитано ли сообщение.

        Возвращает:
            bool - True если is_read == False
        """
        return not self.is_read


class Notification(TimestampedModel):
    """
    Модель уведомления.

    Хранит системные уведомления для пользователей о важных событиях.

    Поля:
        user: ForeignKey - пользователь получатель
        type: CharField - тип уведомления
        title: CharField - заголовок
        message: TextField - сообщение
        is_read: BooleanField - прочитано ли
        read_at: DateTimeField - когда прочитано
        related_order: ForeignKey - связанный заказ (опционально)
        related_task: ForeignKey - связанная задача (опционально)

    Свойства:
        is_unread: bool - True если не прочитано

    Особенности:
        - Автоматические временные метки (TimestampedModel)
        - Разные типы уведомлений
        - Связь с заказами и задачами
    """
    class NotificationType(models.TextChoices):
        """
        Типы уведомлений.

        NEW_ORDER: новый заказ
        NEW_EXPENSE: новый расход
        UNPAID_CLIENT: клиент не оплатил
        OVERDUE_DEBT: долг просрочен
        WORKER_REFUSED: работник отказался
        WORK_AWAITING: работа ожидает подтверждения
        CASH_CHANGE: изменение кассы
        REPORT_READY: отчет готов
        TASK_ASSIGNED: новая задача
        TASK_CHANGED: задача изменена
        TASK_CANCELLED: задача отменена
        WORK_CONFIRMED: работа подтверждена
        WORK_REJECTED: работа отклонена
        NEW_MESSAGE: новое сообщение
        WORK_ACCRUED: личная работа начислена
        MATERIAL_SHORTAGE: нехватка материала
        """
        NEW_ORDER = 'new_order', 'Янги буюртма'
        NEW_EXPENSE = 'new_expense', 'Янги харажат'
        UNPAID_CLIENT = 'unpaid_client', 'Мижоз тўлов қилмади'
        OVERDUE_DEBT = 'overdue_debt', 'Қарз муддати ўтди'
        WORKER_REFUSED = 'worker_refused', 'Ишчи рад этди'
        WORK_AWAITING = 'work_awaiting', 'Иш тасдиқлашни кутмоқда'
        CASH_CHANGE = 'cash_change', 'Касса ўзгариши'
        REPORT_READY = 'report_ready', 'Ҳисобот тайёр'
        TASK_ASSIGNED = 'task_assigned', 'Янги вазифа'
        TASK_CHANGED = 'task_changed', 'Вазифа ўзгартирилди'
        TASK_CANCELLED = 'task_cancelled', 'Вазифа бекор қилинди'
        WORK_CONFIRMED = 'work_confirmed', 'Иш тасдиқланди'
        WORK_REJECTED = 'work_rejected', 'Иш рад этди'
        NEW_MESSAGE = 'new_message', 'Янги хабар'
        WORK_ACCRUED = 'work_accrued', 'Шахсий иш ҳисобланди'
        MATERIAL_SHORTAGE = 'material_shortage', 'Материал етишмовчилиги'

    company = models.ForeignKey('companies.Company', on_delete=models.CASCADE, related_name='notifications', null=True)
    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='notifications')
    type = models.CharField(max_length=30, choices=NotificationType.choices, db_index=True)
    title = models.CharField(max_length=255)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    related_order = models.ForeignKey('orders.Order', on_delete=models.SET_NULL, null=True, blank=True, related_name='notifications')
    related_task = models.ForeignKey('production.Task', on_delete=models.SET_NULL, null=True, blank=True, related_name='notifications')

    class Meta:
        """
        Метаданные модели Notification.

        Атрибуты:
            verbose_name: человекочитаемое имя модели
            verbose_name_plural: множественное число
            ordering: сортировка по убыванию даты создания
            indexes: индексы для оптимизации запросов
        """
        verbose_name = 'Notification'
        verbose_name_plural = 'Notifications'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read']),
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['type']),
        ]

    def __str__(self):
        """
        Строковое представление уведомления.

        Возвращает тип и заголовок.
        """
        return f"{self.get_type_display()} - {self.title}"

    @property
    def is_unread(self):
        """
        Проверяет, не прочитано ли уведомление.

        Возвращает:
            bool - True если is_read == False
        """
        return not self.is_read
