"""
Company model - арендатор (tenant) в мультикомпанийной архитектуре.

Каждая компания полностью изолирована: пользователи, склад, заказы, клиенты,
финансы и все прочие данные привязаны к company. Пользователь одной компании
никогда не видит данные другой (изоляция обеспечивается на уровне queryset
в CompanyScopedViewSet и проверяется в тестах изоляции).

Компании создаёт платформенный супер-администратор (role='superadmin').

ПОДПИСКА (SaaS): каждая компания имеет подписку (план, статус, сроки),
историю изменений (SubscriptionChange) и может быть заморожена. По умолчанию
при создании выдаётся триал (план Free Trial, is_trial=True) на
DEFAULT_SUBSCRIPTION_DAYS дней. Управляет подпиской ТОЛЬКО супер-администратор
через /api/v1/companies/... (активация, продление, смена плана, заморозка).

ЖИЗНЕННЫЙ ЦИКЛ ПОДПИСКИ:
    active --(end прошёл)--> grace --(льготный период прошёл)--> expired

Льготный период (grace_period_days, по умолчанию GRACE_PERIOD_DAYS) — время
после истечения срока, когда бизнес продолжает работать, а владелец получает
предупреждение о скорой блокировке. Платёж обрабатывается вручную супер-
администратором, поэтому жёсткий обрыв в момент истечения был бы враждебен:
льготный период даёт время договориться о продлении. По его окончании задача
Celery (apps.companies.tasks.auto_freeze_expired_subscriptions) переводит
компанию в expired — бизнес-доступ блокируется
(см. apps.core.permissions.SubscriptionAccessPermission), а владелец видит
ограниченный экран «Подписка истекла» вместо рабочего приложения.

СТАТУСЫ однозначны: active (срок в будущем), grace (срок прошёл, льготный
период ещё идёт — доступ сохранён), expired (срок и льготный период прошли —
доступ заблокирован), frozen (ручная заморозка супер-администратором,
независимо от срока), cancelled (терминальный статус). Триал НЕ статус:
триальная компания имеет статус active и флаг is_trial=True (план Free Trial).
"""
from datetime import timedelta
from decimal import Decimal

from django.db import models
from django.utils import timezone

from apps.core.models import TimestampedModel
from apps.core.validators import validate_file_size

# Стандартная длительность подписки при создании компании / активации.
DEFAULT_SUBSCRIPTION_DAYS = 30
# Льготный период после истечения срока (дней). Значение по умолчанию;
# переопределяется per-company в поле grace_period_days.
GRACE_PERIOD_DAYS = 7


class SubscriptionPlan(TimestampedModel):
    """
    Тариф (план) подписки — каталог, из которого выбирает супер-администратор.

    Архитектура рассчитана на несколько тарифов: название, длительность, цена,
    описание и JSON-ограничения. Оплата внешним шлюзом (Stripe/ЮKassa) пока НЕ
    подключена — продление подтверждается супер-администратором вручную, а цена
    носит справочный характер. Ограничения (limits) хранятся, но не
    enforce-ятся: при подключении оплаты и лимитов менять структуру моделей не
    придётся — достаточно включить проверки в бизнес-слой.

    is_default — план, назначаемый новым компаниям (триал). Не более одного.
    """
    name = models.CharField(max_length=100, unique=True, verbose_name='Название')
    code = models.CharField(max_length=50, unique=True, db_index=True, verbose_name='Код')
    duration_days = models.PositiveIntegerField(
        default=DEFAULT_SUBSCRIPTION_DAYS, verbose_name='Длительность (дней)',
    )
    price = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0'), verbose_name='Цена',
    )
    description = models.TextField(blank=True, default='', verbose_name='Описание')
    # Расширяемые ограничения тарифа (например: {"users": 5, "orders": 100}).
    limits = models.JSONField(default=dict, blank=True, verbose_name='Ограничения')
    is_active = models.BooleanField(default=True, db_index=True, verbose_name='Активен')
    is_default = models.BooleanField(default=False, verbose_name='По умолчанию')
    sort_order = models.PositiveIntegerField(default=0, verbose_name='Порядок')

    class Meta:
        verbose_name = 'Тариф'
        verbose_name_plural = 'Тарифы подписки'
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name

    @classmethod
    def get_default_plan(cls):
        """План для новой компании: явный is_default или первый активный."""
        plan = cls.objects.filter(is_default=True, is_active=True).first()
        if plan is None:
            plan = cls.objects.filter(is_active=True).order_by('sort_order', 'id').first()
        return plan


class Company(TimestampedModel):
    class SubscriptionStatus(models.TextChoices):
        """
        Статус подписки компании.

        ACTIVE:   подписка активна (срок в будущем), бизнес работает.
        GRACE:    срок прошёл, действует льготный период (grace_period_days) —
                  бизнес ещё работает, владелец предупреждён о скорой блокировке.
        EXPIRED:  срок и льготный период прошли — компания автоматически
                  заморожена задачей Celery. Бизнес-доступ заблокирован.
        FROZEN:   заморожена вручную супер-администратором (независимо от срока).
        CANCELLED: отменена (терминальный статус, для платформенных нужд).

        Бизнес-доступ блокируется для EXPIRED/FROZEN/CANCELLED. Аккаунты
        пользователей при этом НЕ деактивируются (is_active остаётся True):
        владелец должен иметь возможность войти и увидеть экран
        «Подписка истекла» с инструкцией по продлению.
        """
        ACTIVE = 'active', 'Активна'
        GRACE = 'grace', 'Льготный период'
        EXPIRED = 'expired', 'Истекла'
        FROZEN = 'frozen', 'Заморожена'
        CANCELLED = 'cancelled', 'Отменена'

    name = models.CharField(max_length=255, unique=True, verbose_name='Название')
    is_active = models.BooleanField(default=True, db_index=True, verbose_name='Активен')
    logo = models.ImageField(
        upload_to='company_logos/', blank=True, default='',
        validators=[validate_file_size], verbose_name='Логотип',
    )

    # ── SaaS-подписка ──
    plan = models.ForeignKey(
        SubscriptionPlan, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='companies', verbose_name='Тариф',
    )
    subscription_status = models.CharField(
        max_length=20, choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.ACTIVE, db_index=True, verbose_name='Статус подписки',
    )
    subscription_start = models.DateTimeField(
        null=True, blank=True, verbose_name='Подписка с',
    )
    subscription_end = models.DateTimeField(
        null=True, blank=True, db_index=True, verbose_name='Подписка до',
    )
    # Триал: компания создана с бесплатным периодом и ещё не продлевалась.
    # Снимается любым ручным продлением/активацией супер-администратора.
    is_trial = models.BooleanField(default=True, verbose_name='Триал')
    # Льготный период после истечения срока (дней), настраивается per-company.
    grace_period_days = models.PositiveSmallIntegerField(
        default=GRACE_PERIOD_DAYS, verbose_name='Льготный период (дней)',
    )
    # Последняя активность любого пользователя компании (обновляется в слое
    # JWT-аутентификации с троттлингом — не чаще раза в ACTIVITY_THROTTLE).
    last_activity = models.DateTimeField(null=True, blank=True, verbose_name='Последняя активность')

    class Meta:
        verbose_name = 'Компания'
        verbose_name_plural = 'Компании'
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def grace_end(self):
        """Момент окончания льготного периода (end + grace_period_days)."""
        if self.subscription_end is None:
            return None
        return self.subscription_end + timedelta(days=self.grace_period_days)

    @property
    def is_subscription_active(self):
        """
        Действительно ли подписка работает прямо сейчас.

        True для фактических статусов active и grace (grace — пока льготный
        период не вышел: бизнес продолжает работать, а владелец предупреждён).
        Опирается на effective_subscription_status, а не на формальный
        subscription_status: задача Celery может ещё не отработать, а срок уже
        прошёл — бизнес не должен обрываться в момент истечения, пока идёт
        льготный период (и наоборот: при вышедшем льготном периоде доступ
        закрывается, даже если Celery ещё не перевёл статус в expired).
        """
        return self.effective_subscription_status in (
            self.SubscriptionStatus.ACTIVE,
            self.SubscriptionStatus.GRACE,
        )

    @property
    def effective_subscription_status(self):
        """
        Статус с учётом фактического срока и льготного периода.

        active с прошедшим сроком -> grace (пока идёт льготный период) или
        expired (если grace уже вышел). grace с вышедшим льготным периодом ->
        expired. Это «что пользователь видит прямо сейчас», независимо от того,
        успела ли отработать задача Celery.
        """
        if self.subscription_status == self.SubscriptionStatus.ACTIVE:
            if self.subscription_end is None:
                return self.subscription_status
            if self.subscription_end <= timezone.now():
                grace_end = self.grace_end
                if grace_end is not None and grace_end > timezone.now():
                    return self.SubscriptionStatus.GRACE
                return self.SubscriptionStatus.EXPIRED
            return self.subscription_status
        if self.subscription_status == self.SubscriptionStatus.GRACE:
            grace_end = self.grace_end
            if grace_end is not None and grace_end <= timezone.now():
                return self.SubscriptionStatus.EXPIRED
        return self.subscription_status

    @property
    def subscription_days_left(self):
        """Целых дней до окончания срока (0, если срок уже прошёл)."""
        if self.subscription_end is None:
            return None
        return max((self.subscription_end - timezone.now()).days, 0)

    @property
    def subscription_grace_days_left(self):
        """Целых дней до конца льготного периода (0, если он уже прошёл)."""
        grace_end = self.grace_end
        if grace_end is None:
            return None
        return max((grace_end - timezone.now()).days, 0)

class SubscriptionChange(TimestampedModel):
    """
    История изменений подписки компании (для супер-администратора).

    Каждое действие (активация, продление, установка срока, заморозка,
    разморозка, автоматическое истечение) оставляет запись с прежним и новым
    состоянием. Записи создаются ТОЛЬКО серверным кодом (services/задачей
    Celery) — через API изменить/удалить их нельзя.
    """

    class Action(models.TextChoices):
        ACTIVATED = 'activated', 'Активирована'
        EXTENDED = 'extended', 'Продлена'
        END_SET = 'end_set', 'Срок установлен'
        GRACE_STARTED = 'grace_started', 'Льготный период начался'
        FROZEN = 'frozen', 'Заморожена'
        UNFROZEN = 'unfrozen', 'Разморожена'
        EXPIRED = 'expired', 'Истекла'
        PLAN_CHANGED = 'plan_changed', 'Тариф изменён'
        CANCELLED = 'cancelled', 'Отменена'

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE,
        related_name='subscription_changes', verbose_name='Компания',
    )
    action = models.CharField(max_length=20, choices=Action.choices, db_index=True, verbose_name='Действие')
    old_status = models.CharField(max_length=20, blank=True, verbose_name='Было')
    new_status = models.CharField(max_length=20, blank=True, verbose_name='Стало')
    old_end = models.DateTimeField(null=True, blank=True, verbose_name='Было до')
    new_end = models.DateTimeField(null=True, blank=True, verbose_name='Стало до')
    days_added = models.PositiveIntegerField(null=True, blank=True, verbose_name='Добавлено дней')
    old_plan = models.CharField(max_length=100, blank=True, verbose_name='Был тариф')
    new_plan = models.CharField(max_length=100, blank=True, verbose_name='Стал тариф')
    actor = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='subscription_changes', verbose_name='Кто изменил',
    )
    note = models.CharField(max_length=255, blank=True, verbose_name='Комментарий')

    class Meta:
        verbose_name = 'Изменение подписки'
        verbose_name_plural = 'История подписок'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['company', 'created_at']),
        ]

    def __str__(self):
        return f'{self.company_id} {self.action}'
