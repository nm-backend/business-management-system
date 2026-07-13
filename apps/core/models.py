"""
Core models - базовые абстрактные модели для всего проекта.

Этот модуль содержит фундаментальные модели, которые используются
в других приложениях как базовые классы для обеспечения единообразия.
"""
from django.db import models


class TimestampedModel(models.Model):
    """
    Абстрактная модель с автоматическими временными метками.

    Добавляет поля created_at и updated_at ко всем наследуемым моделям.
    Используется для отслеживания времени создания и изменения записей.

    Поля:
        created_at: DateTimeField - время создания записи (автоматически)
        updated_at: DateTimeField - время последнего обновления (автоматически)
    """
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

class SoftDeleteModel(models.Model):
    """
    Абстрактная модель для мягкого удаления записей.

    Вместо физического удаления записи помечаются как архивированные.
    Это позволяет сохранять историю и восстанавливать данные при необходимости.

    Поля:
        is_archived: BooleanField - флаг архивации (индексирован для быстрого поиска)
        archived_at: DateTimeField - время архивации

    Методы:
        archive(): помечает запись как архивированную
        restore(): восстанавливает архивированную запись
    """
    is_archived = models.BooleanField(default=False, db_index=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    def archive(self):
        """
        Помечает запись как архивированную.

        Устанавливает is_archived=True и записывает текущее время в archived_at.
        Использует update_fields для оптимизации SQL запроса.
        """
        from django.utils import timezone
        self.is_archived = True
        self.archived_at = timezone.now()
        self.save(update_fields=['is_archived', 'archived_at'])

    def restore(self):
        """
        Восстанавливает архивированную запись.

        Сбрасывает флаг архивации и очищает время архивации.
        """
        self.is_archived = False
        self.archived_at = None
        self.save(update_fields=['is_archived', 'archived_at'])

class Currency(TimestampedModel):
    """
    Модель валюты для мультивалютной системы.

    Хранит информацию о валютах, используемых в системе.
    Поддерживает установку валюты по умолчанию и деактивацию валют.

    Поля:
        code: CharField(3) - ISO 4217 код валюты (уникальный, например: KGS, USD, EUR)
        name: CharField(100) - полное название валюты
        symbol: CharField(10) - символ валюты для отображения (например: $, €, с)
        is_default: BooleanField - флаг валюты по умолчанию (только одна может быть True)
        is_active: BooleanField - флаг активности валюты
        decimal_places: PositiveSmallIntegerField - количество десятичных знаков (по умолчанию 2)

    Особенности:
        - При сохранении автоматически снимает флаг is_default с других валют
        - Используется для конвертации цен и отображения в разных валютах
    """
    code = models.CharField(max_length=3, unique=True, help_text='ISO 4217 code (e.g. KGS, USD)')
    name = models.CharField(max_length=100, help_text='Currency name')
    symbol = models.CharField(max_length=10, help_text='Currency symbol')
    is_default = models.BooleanField(default=False, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    decimal_places = models.PositiveSmallIntegerField(default=2)

    class Meta:
        verbose_name = 'Currency'
        verbose_name_plural = 'Currencies'
        ordering = ['-is_default', 'code']

    def __str__(self):
        return f'{self.code} ({self.symbol})'

    def save(self, *args, **kwargs):
        """
        Переопределенный метод save для обеспечения единственности валюты по умолчанию.

        Если устанавливается is_default=True, автоматически сбрасывает этот флаг
        у всех других валют. Это гарантирует, что всегда будет только одна
        валюта по умолчанию в системе.
        """
        if self.is_default:
            Currency.objects.filter(is_default=True).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)

class ExchangeRate(TimestampedModel):
    """
    Модель курса обмена валюты.

    Хранит исторические курсы обмена между валютами.
    Позволяет получать актуальный курс на определенную дату.

    Поля:
        from_currency: ForeignKey - исходная валюта
        to_currency: ForeignKey - целевая валюта
        rate: DecimalField - курс обмена (сколько единиц to_currency за 1 from_currency)
        effective_date: DateField - дата, с которой действует курс

    Особенности:
        - Уникальность: (from_currency, to_currency, effective_date)
        - Сортировка по дате убывания для получения последнего курса
        - Метод get_rate() для получения актуального курса на дату
    """
    from_currency = models.ForeignKey(Currency, on_delete=models.CASCADE, related_name='rates_from')
    to_currency = models.ForeignKey(Currency, on_delete=models.CASCADE, related_name='rates_to')
    rate = models.DecimalField(max_digits=12, decimal_places=6, help_text='Exchange rate')
    effective_date = models.DateField(db_index=True)

    class Meta:
        verbose_name = 'Exchange Rate'
        verbose_name_plural = 'Exchange Rates'
        ordering = ['-effective_date']
        unique_together = ['from_currency', 'to_currency', 'effective_date']

    def __str__(self):
        return f'{self.from_currency.code} -> {self.to_currency.code}: {self.rate} ({self.effective_date})'

    @classmethod
    def get_rate(cls, from_code, to_code, date=None):
        """
        Получает актуальный курс обмена на указанную дату.

        Аргументы:
            from_code: str - код исходной валюты (например: 'USD')
            to_code: str - код целевой валюты (например: 'KGS')
            date: date - дата для получения курса (по умолчанию сегодня)

        Возвращает:
            ExchangeRate или None - последний курс на указанную дату или None если не найден

        Логика:
            - Ищет курсы с effective_date <= указанной даты
            - Возвращает самый свежий курс (сортировка по дате убывания)
        """
        from django.utils import timezone
        if date is None:
            date = timezone.now().date()
        try:
            return cls.objects.filter(
                from_currency__code=from_code,
                to_currency__code=to_code,
                effective_date__lte=date
            ).order_by('-effective_date').first()
        except cls.DoesNotExist:
            return None
