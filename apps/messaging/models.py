"""
Messaging models — внутренний корпоративный чат и системные уведомления.

Чат построен вокруг модели «беседы» (Conversation), чтобы одинаково
поддерживать общий чат компании, личные сообщения и (в будущем) группы.

БЕЗОПАСНОСТЬ (multi-tenant): у каждой беседы и каждого сообщения есть
company. Все выборки фильтруются и по company, и по участию пользователя
(ConversationParticipant), поэтому компания A физически не может получить
беседы или сообщения компании B даже через прямой API-запрос.
"""
from django.db import models

from apps.core.models import TimestampedModel


class Conversation(TimestampedModel):
    """
    Беседа (чат): общий чат компании, личный диалог или группа.

    Виды (kind):
        GENERAL — общий чат компании (ровно один на компанию, участники —
                  все сотрудники компании).
        DIRECT  — личный диалог двух сотрудников одной компании.
        GROUP   — групповой чат (задел на будущее).

    Поля:
        company: FK — компания-владелец (арендатор). Ключ изоляции.
        kind: вид беседы.
        title: название (для общего/группового чата; у DIRECT пустое —
               имя показывается как имя собеседника).
        created_by: кто создал беседу (null для авто-созданного общего чата).
    """
    class Kind(models.TextChoices):
        GENERAL = 'general', 'Общий чат компании'
        DIRECT = 'direct', 'Личный диалог'
        GROUP = 'group', 'Групповой чат'

    company = models.ForeignKey(
        'companies.Company', on_delete=models.CASCADE, related_name='conversations', verbose_name='Компания'
    )
    kind = models.CharField(max_length=10, choices=Kind.choices, db_index=True, verbose_name='Вид')
    title = models.CharField(max_length=255, blank=True, default='', verbose_name='Заголовок')
    created_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='created_conversations', verbose_name='Кем создано'
    )

    class Meta:
        verbose_name = 'Беседа'
        verbose_name_plural = 'Беседы'
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['company', 'kind']),
            models.Index(fields=['company', '-updated_at']),
        ]
        constraints = [
            # Ровно один общий чат на компанию.
            models.UniqueConstraint(
                fields=['company'],
                condition=models.Q(kind='general'),
                name='unique_general_chat_per_company',
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} #{self.pk} ({self.company_id})"


class ConversationParticipant(TimestampedModel):
    """
    Участник беседы.

    Хранит членство пользователя в беседе и указатель прочтения
    (last_read_at) — по нему считаются непрочитанные сообщения:
    непрочитанные = сообщения беседы, созданные позже last_read_at
    и отправленные не самим пользователем.
    """
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name='participants', verbose_name='Беседа'
    )
    user = models.ForeignKey(
        'accounts.User', on_delete=models.CASCADE, related_name='chat_participations', verbose_name='Пользователь'
    )
    last_read_at = models.DateTimeField(null=True, blank=True, verbose_name='Прочитано до')

    class Meta:
        verbose_name = 'Участник беседы'
        verbose_name_plural = 'Участники беседы'
        constraints = [
            models.UniqueConstraint(
                fields=['conversation', 'user'],
                name='unique_participant_per_conversation',
            ),
        ]
        indexes = [
            models.Index(fields=['user', 'conversation']),
        ]

    def __str__(self):
        return f"{self.user_id} @ conversation {self.conversation_id}"


class ChatMessage(TimestampedModel):
    """
    Сообщение в беседе.

    company денормализована из беседы для быстрой и надёжной фильтрации
    изоляции (и фильтров в админке).
    """
    company = models.ForeignKey(
        'companies.Company', on_delete=models.CASCADE, related_name='chat_messages', verbose_name='Компания'
    )
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name='messages',
        verbose_name='Беседа',
    )
    sender = models.ForeignKey(
        'accounts.User', on_delete=models.CASCADE, related_name='chat_messages', verbose_name='Отправитель'
    )
    content = models.TextField(verbose_name='Текст сообщения')

    class Meta:
        verbose_name = 'Сообщение чата'
        verbose_name_plural = 'Сообщения чата'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['conversation', 'created_at']),
            models.Index(fields=['company', 'created_at']),
        ]

    def __str__(self):
        return f"{self.sender_id}: {self.content[:40]}"


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
        SUBSCRIPTION_EXPIRING_SOON: подписка истекает через 7 дней
        SUBSCRIPTION_EXPIRING: подписка истекает через 1 день
        SUBSCRIPTION_RENEWAL_REQUEST: владелец запросил продление подписки
        SUBSCRIPTION_GRACE_STARTED: начался льготный период (срок прошёл,
                                    бизнес ещё работает до конца льготного срока)
        SUBSCRIPTION_EXPIRED: подписка истекла, доступ ограничен
        SUBSCRIPTION_PLAN_CHANGED: тариф компании изменён супер-администратором
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
        SUBSCRIPTION_EXPIRING_SOON = 'subscription_expiring_soon', 'Обуна 7 кундан сўнг тугайди'
        SUBSCRIPTION_EXPIRING = 'subscription_expiring', 'Обуна 1 кундан сўнг тугайди'
        SUBSCRIPTION_FROZEN = 'subscription_frozen', 'Подписка истекла'
        SUBSCRIPTION_RENEWED = 'subscription_renewed', 'Подписка продлена'
        SUBSCRIPTION_RENEWAL_REQUEST = 'subscription_renewal_request', 'Обунани узайтириш сўрови'
        SUBSCRIPTION_EXTENDED = 'subscription_extended', 'Обуна узайтирилди'
        SUBSCRIPTION_GRACE_STARTED = 'subscription_grace_started', 'Имтиёзли давр бошланди'
        SUBSCRIPTION_EXPIRED = 'subscription_expired', 'Обуна тугади'
        SUBSCRIPTION_PLAN_CHANGED = 'subscription_plan_changed', 'Тариф ўзгартирилди'

    company = models.ForeignKey('companies.Company', on_delete=models.CASCADE, related_name='notifications', null=True, verbose_name='Компания')
    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='notifications', verbose_name='Пользователь')
    type = models.CharField(max_length=30, choices=NotificationType.choices, db_index=True, verbose_name='Тип')
    title = models.CharField(max_length=255, verbose_name='Заголовок')
    message = models.TextField(verbose_name='Сообщение')
    is_read = models.BooleanField(default=False, verbose_name='Прочитано')
    read_at = models.DateTimeField(null=True, blank=True, verbose_name='Когда прочитано')
    related_order = models.ForeignKey('orders.Order', on_delete=models.SET_NULL, null=True, blank=True, related_name='notifications', verbose_name='Связанный заказ')
    related_task = models.ForeignKey('production.Task', on_delete=models.SET_NULL, null=True, blank=True, related_name='notifications', verbose_name='Связанная задача')

    class Meta:
        """
        Метаданные модели Notification.

        Атрибуты:
            verbose_name: человекочитаемое имя модели
            verbose_name_plural: множественное число
            ordering: сортировка по убыванию даты создания
            indexes: индексы для оптимизации запросов
        """
        verbose_name = 'Уведомление'
        verbose_name_plural = 'Уведомления'
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


class WsTicket(TimestampedModel):
    """
    Одноразовый тикет для WebSocket-соединения чата.

    Access-токен нельзя передавать в query-строке WebSocket-URL: он попадает
    в логи прокси/балансировщика и течёт с них. Поэтому клиент запрашивает
    короткоживущий тикет (TTL ~60 секунд) по REST с обычным заголовком
    Authorization, а WebSocket открывает только с тикетом.

    Тикет одноразовый: middleware проверяет и сразу помечает использованным,
    поэтому украденный тикет не пригоден для второго соединения.
    """
    company = models.ForeignKey(
        'companies.Company', on_delete=models.CASCADE, related_name='ws_tickets', verbose_name='Компания'
    )
    user = models.ForeignKey(
        'accounts.User', on_delete=models.CASCADE, related_name='ws_tickets', verbose_name='Пользователь'
    )
    ticket = models.CharField(max_length=64, unique=True, db_index=True, verbose_name='Тикет')
    expires_at = models.DateTimeField(db_index=True, verbose_name='Действует до')
    used = models.BooleanField(default=False, verbose_name='Использован')

    class Meta:
        verbose_name = 'WS тикет'
        verbose_name_plural = 'WS тикеты'
        ordering = ['-created_at']

    def __str__(self):
        return f'WS ticket {self.user_id} ({"used" if self.used else "active"})'
