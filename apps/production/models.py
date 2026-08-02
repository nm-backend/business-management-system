"""
Production models - управление производством и задачами.

Этот модуль содержит модели для управления производственными задачами,
работами работников и подтверждением выполненной работы.
"""
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from apps.core.models import TimestampedModel
from apps.core.validators import validate_file_size
from apps.warehouse.models import UnitChoices


class TaskStatus(models.TextChoices):
    """
    Статусы задачи.

    PENDING: ожидает принятия работником
    ACCEPTED: принята работником
    REFUSED: отклонена работником
    IN_PROGRESS: в работе
    COMPLETED: выполнена, ожидает подтверждения
    CONFIRMED: подтверждена
    REJECTED: отклонена администратором/владельцем
    CANCELLED: отменена
    """
    PENDING = 'pending', 'Кутилмоқда'
    ACCEPTED = 'accepted', 'Қабул қилинди'
    REFUSED = 'refused', 'Рад этилди'
    IN_PROGRESS = 'in_progress', 'Жараёнда'
    COMPLETED = 'completed', 'Бажарилди'
    CONFIRMED = 'confirmed', 'Тасдиқланди'
    REJECTED = 'rejected', 'Рад этилди'
    CANCELLED = 'cancelled', 'Бекор қилинди'


class RefusalReason(models.TextChoices):
    """
    Причины отказа от задачи.

    MATERIAL_INSUFFICIENT: материала недостаточно
    NO_TIME: нет времени
    WRONG_SIZE: неправильный размер
    NEED_HELPER: нужен помощник
    EQUIPMENT_BUSY: оборудование занято
    OTHER: другая причина
    """
    MATERIAL_INSUFFICIENT = 'material_insufficient', 'Материал етарли эмас'
    NO_TIME = 'no_time', 'Вақтим йўқ'
    WRONG_SIZE = 'wrong_size', 'Ўлчам нотўғри'
    NEED_HELPER = 'need_helper', 'Ёрдамчи керак'
    EQUIPMENT_BUSY = 'equipment_busy', 'Ускуна банд'
    OTHER = 'other', 'Бошқа сабаб'


class Task(TimestampedModel):
    """
    Модель задачи для работника.

    Хранит информацию о задачах, назначенных работникам,
    связывает с заказами и производством.

    Поля:
        order: ForeignKey - связанный заказ
        worker: ForeignKey - назначенный работник
        assigned_by: ForeignKey - кто назначил задачу
        status: CharField - статус задачи
        refusal_reason: CharField - причина отказа
        refusal_comment: TextField - комментарий отказа
        assigned_at: DateTimeField - когда назначена
        accepted_at: DateTimeField - когда принята
        completed_at: DateTimeField - когда выполнена
        confirmed_at: DateTimeField - когда подтверждена
        confirmed_by: ForeignKey - кто подтвердил
        rejection_comment: TextField - комментарий при отклонении
        is_self_assigned: BooleanField - самостоятельная работа

    Свойства:
        is_overdue: bool - просрочена ли задача
        duration_hours: DecimalField - длительность в часах

    Особенности:
        - Автоматические временные метки (TimestampedModel)
        - Отслеживание всего жизненного цикла задачи
        - Связь с заказами и работниками
    """
    company = models.ForeignKey('companies.Company', on_delete=models.CASCADE, related_name='tasks', null=True, verbose_name='Компания')
    order = models.ForeignKey('orders.Order', on_delete=models.CASCADE, related_name='tasks', null=True, blank=True, verbose_name='Заказ')
    worker = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='tasks', verbose_name='Работник')
    assigned_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, related_name='assigned_tasks', verbose_name='Кем назначено')
    status = models.CharField(max_length=20, choices=TaskStatus.choices, default=TaskStatus.PENDING, db_index=True, verbose_name='Статус')
    refusal_reason = models.CharField(max_length=30, choices=RefusalReason.choices, blank=True, default='', verbose_name='Причина отказа')
    refusal_comment = models.TextField(blank=True, default='', verbose_name='Комментарий к отказу')
    assigned_at = models.DateTimeField(auto_now_add=True, verbose_name='Назначено')
    accepted_at = models.DateTimeField(null=True, blank=True, verbose_name='Принято в работу')
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name='Завершено')
    confirmed_at = models.DateTimeField(null=True, blank=True, verbose_name='Подтверждено')
    confirmed_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='confirmed_tasks', verbose_name='Кем подтверждено')
    rejection_comment = models.TextField(blank=True, default='', verbose_name='Комментарий к отклонению')
    is_self_assigned = models.BooleanField(default=False, verbose_name='Взято работником самостоятельно')

    class Meta:
        """
        Метаданные модели Task.

        Атрибуты:
            verbose_name: человекочитаемое имя модели
            verbose_name_plural: множественное число
            ordering: сортировка по убыванию даты назначения
            indexes: индексы для оптимизации запросов
        """
        verbose_name = 'Задача'
        verbose_name_plural = 'Задачи'
        ordering = ['-assigned_at']
        indexes = [
            models.Index(fields=['worker', 'status']),
            models.Index(fields=['status', 'assigned_at']),
        ]

    def __str__(self):
        """
        Строковое представление задачи.

        Возвращает информацию о задаче с работником и статусом.
        """
        return f"Task #{self.id} - {self.worker.username} ({self.get_status_display()})"

    def accept(self):
        """Работник принимает задачу; связанный заказ переходит в 'принят работником'."""
        from django.utils import timezone
        self.status = TaskStatus.ACCEPTED
        self.accepted_at = timezone.now()
        self.save(update_fields=['status', 'accepted_at'])
        if self.order:
            self.order.status = self.order.Status.ACCEPTED
            self.order.save(update_fields=['status'])

    def refuse(self, reason, comment=''):
        """Работник отказывается от задачи; заказ переходит в 'работник отказался'."""
        self.status = TaskStatus.REFUSED
        self.refusal_reason = reason
        self.refusal_comment = comment
        self.save(update_fields=['status', 'refusal_reason', 'refusal_comment'])
        if self.order:
            self.order.status = self.order.Status.WORKER_REFUSED
            self.order.save(update_fields=['status'])

    def complete(self):
        """Работа сдана на проверку; заказ переходит в 'ожидает подтверждения'."""
        from django.utils import timezone
        self.status = TaskStatus.COMPLETED
        self.completed_at = timezone.now()
        self.save(update_fields=['status', 'completed_at'])
        if self.order:
            self.order.status = self.order.Status.AWAITING_CONFIRMATION
            self.order.save(update_fields=['status'])

    def confirm(self, confirmed_by):
        """Администратор/владелец подтверждает задачу; заказ становится готовым."""
        from django.utils import timezone
        self.status = TaskStatus.CONFIRMED
        self.confirmed_at = timezone.now()
        self.confirmed_by = confirmed_by
        self.save(update_fields=['status', 'confirmed_at', 'confirmed_by'])
        if self.order:
            self.order.status = self.order.Status.READY
            self.order.save(update_fields=['status'])


class WorkRecord(TimestampedModel):
    """
    Модель записи о выполненной работе.

    Хранит информацию о работе, выполненной работником,
    для подтверждения и начисления оплаты.

    Поля:
        task: ForeignKey - связанная задача
        worker: ForeignKey - работник
        product: ForeignKey - готовый продукт
        quantity: DecimalField - количество выполненной работы
        unit: CharField - единица измерения
        photo: ImageField - фото результата
        comment: TextField - комментарий работника
        status: CharField - статус (ожидает подтверждения/подтверждена/отклонена)
        confirmed_by: ForeignKey - кто подтвердил
        confirmed_at: DateTimeField - когда подтверждена
        rejection_reason: TextField - причина отклонения
        labor_cost: DecimalField - стоимость труда (ФИНАНСОВОЕ ПОЛЕ)

    Свойства:
        is_confirmed: bool - подтверждена ли работа

    Особенности:
        - Автоматические временные метки (TimestampedModel)
        - Фото результата работы
        - Подтверждение администратором или владельцем
    """
    class WorkStatus(models.TextChoices):
        """
        Статусы работы.

        AWAITING_CONFIRMATION: ожидает подтверждения
        CONFIRMED: подтверждена
        REJECTED: отклонена
        """
        AWAITING_CONFIRMATION = 'awaiting_confirmation', 'Тасдиқлаш кутилмоқда'
        CONFIRMED = 'confirmed', 'Тасдиқланди'
        REJECTED = 'rejected', 'Рад этилди'

    company = models.ForeignKey('companies.Company', on_delete=models.CASCADE, related_name='work_records', null=True, verbose_name='Компания')
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='work_records', null=True, blank=True, verbose_name='Задача')
    worker = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='work_records', verbose_name='Работник')
    product = models.ForeignKey('warehouse.FinishedProduct', on_delete=models.SET_NULL, null=True, blank=True, related_name='work_records', verbose_name='Товар')
    quantity = models.DecimalField(max_digits=15, decimal_places=3, verbose_name='Количество')
    # Брак по макету «Ишни якунлаш»: рабочий указывает его отдельно от годного.
    # Сырьё расходуется и на брак тоже, а на склад готовой продукции попадает
    # только годное — без этого поля материал, ушедший в брак, не списывался
    # и остаток сырья был завышен.
    defect_quantity = models.DecimalField(
        max_digits=15, decimal_places=3, default=0,
        validators=[MinValueValidator(Decimal('0'))], verbose_name='Брак')
    unit = models.CharField(max_length=20, choices=UnitChoices.choices, verbose_name='Единица измерения')
    photo = models.ImageField(upload_to='production/work_photos/', blank=True, null=True, validators=[validate_file_size], verbose_name='Фото')
    comment = models.TextField(blank=True, default='', verbose_name='Комментарий')
    status = models.CharField(max_length=30, choices=WorkStatus.choices, default=WorkStatus.AWAITING_CONFIRMATION, db_index=True, verbose_name='Статус')
    confirmed_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='confirmed_works', verbose_name='Кем подтверждено')
    confirmed_at = models.DateTimeField(null=True, blank=True, verbose_name='Подтверждено')
    rejection_reason = models.TextField(blank=True, default='', verbose_name='Причина отклонения')
    labor_cost = models.DecimalField(max_digits=15, decimal_places=2, default=0, verbose_name='Стоимость работы')  # ФИНАНСОВОЕ ПОЛЕ

    class Meta:
        """
        Метаданные модели WorkRecord.

        Атрибуты:
            verbose_name: человекочитаемое имя модели
            verbose_name_plural: множественное число
            ordering: сортировка по убыванию даты создания
            indexes: индексы для оптимизации запросов
        """
        verbose_name = 'Запись о работе'
        verbose_name_plural = 'Записи о работе'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['worker', 'status']),
            models.Index(fields=['status', 'created_at']),
        ]

    def __str__(self):
        """
        Строковое представление записи о работе.

        Возвращает информацию о работе с работником и статусом.
        """
        return f"Work #{self.id} - {self.worker.username} ({self.get_status_display()})"

    @property
    def is_confirmed(self):
        """
        Проверяет, подтверждена ли работа.

        Возвращает:
            bool - True если status == 'confirmed'
        """
        return self.status == self.WorkStatus.CONFIRMED
