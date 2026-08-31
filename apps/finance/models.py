"""
Finance models - управление финансами.

Этот модуль содержит модели для управления расходами,
оплатой работников и финансовой аналитикой.

ВАЖНО: Все финансовые данные доступны только владельцу (owner).
"""
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _
from apps.core.models import TimestampedModel
from apps.core.validators import validate_not_future, validate_file_size
from apps.warehouse.models import UnitChoices


class ExpenseCategory(models.TextChoices):
    RENT = 'rent', _('Ижара')
    ELECTRICITY = 'electricity', _('Электр энергия')
    WATER = 'water', _('Сув')
    TRANSPORT = 'transport', _('Транспорт')
    DELIVERY = 'delivery', _('Етказиб бериш')
    TAXES = 'taxes', _('Солиқлар')
    SALARY = 'salary', _('Ишчилар иш ҳақи')
    ADVANCE = 'advance', _('Ишчиларга аванс')
    EQUIPMENT_REPAIR = 'equipment_repair', _('Ускуна таъмири')
    TOOLS = 'tools', _('Асбоб сотиб олиш')
    CONSUMABLES = 'consumables', _('Сарфлаш материаллари')
    MATERIAL_LOSS = 'material_loss', _('Материал йўқотиш')
    DEFECT = 'defect', _('Брак')
    UNFORESEEN = 'unforeseen', _('Кутилмаган харажатлар')
    OWNER_WITHDRAWAL = 'owner_withdrawal', _('Эгасининг шахсий чиқими')
    WORKER_DEBT = 'worker_debt', _('Ишчилар қарзлари')
    CLIENT_REFUND = 'client_refund', _('Мижозларга қайтариш')
    OTHER = 'other', _('Бошқа')


class PaymentMethod(models.TextChoices):
    CASH = 'cash', _('Нақд')
    CARD = 'card', _('Карта')
    TRANSFER = 'transfer', _('Ўтказма')
    OTHER = 'other', _('Бошқа')


class Expense(TimestampedModel):
    """
    Модель расхода.

    Хранит информацию о всех расходах компании.
    Доступна только владельцу.

    Поля:
        category: CharField - категория расхода
        amount: DecimalField - сумма расхода
        date: DateField - дата расхода
        comment: TextField - комментарий
        receipt_photo: ImageField - фото чека
        created_by: ForeignKey - кто добавил расход
        payment_method: CharField - способ оплаты

    Особенности:
        - Автоматические временные метки (TimestampedModel)
        - Фото чека для подтверждения
        - Категоризация расходов
    """
    company = models.ForeignKey('companies.Company', on_delete=models.CASCADE, related_name='expenses', null=True, verbose_name='Компания')
    category = models.CharField(max_length=30, choices=ExpenseCategory.choices, db_index=True, verbose_name='Категория')
    amount = models.DecimalField(max_digits=15, decimal_places=2,
                                 validators=[MinValueValidator(Decimal('0.01'))], verbose_name='Сумма')
    date = models.DateField(db_index=True, validators=[validate_not_future],
                            verbose_name='Дата')
    comment = models.TextField(blank=True, default='', verbose_name='Комментарий')
    receipt_photo = models.ImageField(upload_to='finance/receipts/', blank=True, null=True, validators=[validate_file_size], verbose_name='Фото чека')
    created_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, related_name='expenses', verbose_name='Кем добавлено')
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.CASH, verbose_name='Способ оплаты')

    class Meta:
        """
        Метаданные модели Expense.

        Атрибуты:
            verbose_name: человекочитаемое имя модели
            verbose_name_plural: множественное число
            ordering: сортировка по дате и созданию
            indexes: индексы для оптимизации запросов
        """
        verbose_name = 'Расход'
        verbose_name_plural = 'Расходы'
        ordering = ['-date', '-created_at']
        indexes = [
            models.Index(fields=['category', 'date']),
            models.Index(fields=['date']),
        ]

    def __str__(self):
        """
        Строковое представление расхода.

        Возвращает категорию и сумму.
        """
        return f"{self.get_category_display()} - {self.amount}"


class LaborRate(TimestampedModel):
    """
    Модель ставки оплаты труда.

    Хранит ставки оплаты за единицу работы для разных типов продукции.
    Доступна только владельцу.

    Поля:
        product: ForeignKey - готовая продукция
        operation: CharField - тип операции (резка, полировка и т.д.)
        rate_per_unit: DecimalField - ставка за единицу
        unit: CharField - единица измерения

    Особенности:
        - Автоматические временные метки (TimestampedModel)
        - Разные ставки для разных операций
    """
    class OperationType(models.TextChoices):
        CUTTING = 'cutting', _('Кесиш')
        POLISHING = 'polishing', _('Сийлаш')
        MOUNTING = 'mounting', _('Монтаж')
        PACKING = 'packing', _('Қутлаш')
        OTHER = 'other', _('Бошқа')

    company = models.ForeignKey('companies.Company', on_delete=models.CASCADE, related_name='labor_rates', null=True, verbose_name='Компания')
    product = models.ForeignKey('warehouse.FinishedProduct', on_delete=models.CASCADE, related_name='labor_rates', verbose_name='Товар')
    operation = models.CharField(max_length=20, choices=OperationType.choices, verbose_name='Операция')
    rate_per_unit = models.DecimalField(max_digits=15, decimal_places=2,
                                        validators=[MinValueValidator(Decimal('0.01'))], verbose_name='Ставка за единицу')
    unit = models.CharField(max_length=20, choices=UnitChoices.choices, verbose_name='Единица измерения')

    class Meta:
        """
        Метаданные модели LaborRate.

        Атрибуты:
            verbose_name: человекочитаемое имя модели
            verbose_name_plural: множественное число
            ordering: сортировка по продукту и операции
            unique_together: уникальная комбинация продукта и операции
        """
        verbose_name = 'Ставка оплаты труда'
        verbose_name_plural = 'Ставки оплаты труда'
        ordering = ['product', 'operation']
        unique_together = ['product', 'operation']

    def __str__(self):
        """
        Строковое представление ставки.

        Возвращает продукт, операцию и ставку.
        """
        return f"{self.product.name} - {self.get_operation_display()}: {self.rate_per_unit} / {self.unit}"


class WorkerPayment(TimestampedModel):
    """
    Модель оплаты работника.

    Хранит информацию о выплатах работникам.
    Доступна только владельцу.

    Поля:
        worker: ForeignKey - работник
        amount: DecimalField - сумма выплаты
        payment_date: DateField - дата выплаты
        payment_type: CharField - тип выплаты (зарплата, аванс, премия)
        comment: TextField - комментарий
        created_by: ForeignKey - кто создал запись

    Особенности:
        - Автоматические временные метки (TimestampedModel)
        - Разные типы выплат
    """
    class PaymentType(models.TextChoices):
        SALARY = 'salary', _('Иш ҳақи')
        ADVANCE = 'advance', _('Аванс')
        BONUS = 'bonus', _('Мукофот')
        OTHER = 'other', _('Бошқа')

    company = models.ForeignKey('companies.Company', on_delete=models.CASCADE, related_name='worker_payments', null=True, verbose_name='Компания')
    worker = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='payments', verbose_name='Работник')
    amount = models.DecimalField(max_digits=15, decimal_places=2,
                                 validators=[MinValueValidator(Decimal('0.01'))], verbose_name='Сумма')
    # Будущая дата запрещена, как у Expense: выплата будущим числом искажает
    # расчёты (прибыль, кассу) и ничем не контролируется.
    payment_date = models.DateField(db_index=True, validators=[validate_not_future], verbose_name='Дата оплаты')
    payment_type = models.CharField(max_length=20, choices=PaymentType.choices, default=PaymentType.SALARY, verbose_name='Вид выплаты')
    comment = models.TextField(blank=True, default='', verbose_name='Комментарий')
    created_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, related_name='created_payments', verbose_name='Кем добавлено')

    class Meta:
        """
        Метаданные модели WorkerPayment.

        Атрибуты:
            verbose_name: человекочитаемое имя модели
            verbose_name_plural: множественное число
            ordering: сортировка по дате выплаты и созданию
            indexes: индексы для оптимизации запросов
        """
        verbose_name = 'Выплата работнику'
        verbose_name_plural = 'Выплаты работникам'
        ordering = ['-payment_date', '-created_at']
        indexes = [
            models.Index(fields=['worker', 'payment_date']),
            models.Index(fields=['payment_date']),
        ]

    def __str__(self):
        """
        Строковое представление выплаты.

        Возвращает работника, сумму и тип выплаты.
        """
        return f"{self.worker.username} - {self.amount} ({self.get_payment_type_display()})"
