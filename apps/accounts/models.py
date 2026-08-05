"""
Custom User model with role-based access control.

Этот модуль содержит кастомную модель пользователя, которая расширяет
AbstractUser для поддержки ролевой системы и дополнительных полей,
необходимых для бизнес-логики SkladPro.

Ролевая система:
- owner: владелец бизнеса (полный доступ)
- admin: администратор (управление складом и работниками)
- worker: работник (ограниченный доступ)
"""
import secrets

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

from apps.core.models import TimestampedModel
from apps.core.validators import validate_file_size

from .managers import UserManager

# Алфавит без похожих символов (0/O, 1/I) — код удобно диктовать и вводить.
_ACCESS_KEY_ALPHABET = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ'


def generate_access_key_code():
    """Генерирует код-приглашение вида SKP-4A8F-72KD-91XQ."""
    groups = [''.join(secrets.choice(_ACCESS_KEY_ALPHABET) for _ in range(4)) for _ in range(3)]
    return 'SKP-' + '-'.join(groups)


class Skill(TimestampedModel):
    """
    Профессиональный навык сотрудника (Python, Sales, Manager, Designer и т.д.).

    Каталог навыков компании. Навык привязан к компании (арендатору), поэтому
    одна компания НИКОГДА не видит навыки другой. Изоляция обеспечивается на
    уровне queryset во view (SkillViewSet.get_queryset фильтрует по
    request.user.company_id) и проверяется тестами изоляции.

    Поля:
        company: ForeignKey - компания-владелец (арендатор). Ключ изоляции.
        name: CharField - название навыка (уникально в рамках компании).
        category: CharField - необязательная категория для группировки
                  (например: «Технологии», «Продажи»).

    Особенности:
        - Наследует TimestampedModel (created_at/updated_at).
        - Уникальность имени в пределах компании (две разные компании могут
          иметь навык с одинаковым именем).
    """
    company = models.ForeignKey(
        'companies.Company',
        on_delete=models.CASCADE,
        null=True,
        related_name='skills',
        verbose_name='Компания',
    )
    name = models.CharField(max_length=100, verbose_name='Название навыка')
    category = models.CharField(
        max_length=50, blank=True, default='', verbose_name='Категория',
    )

    class Meta:
        verbose_name = 'Навык (специализация)'
        verbose_name_plural = 'Навыки (специализации)'
        ordering = ['name']
        constraints = [
            # Имя навыка уникально в пределах компании, но не глобально.
            models.UniqueConstraint(
                fields=['company', 'name'],
                name='accounts_skill_unique_per_company',
            ),
        ]
        indexes = [
            models.Index(fields=['company', 'name']),
        ]

    def __str__(self):
        """Строковое представление навыка — его название."""
        return self.name


class User(AbstractUser):
    """
    Кастомная модель пользователя с ролевой системой.

    Расширяет стандартную Django модель AbstractUser дополнительными
    полями для бизнес-логики и системой контроля доступа на основе ролей.

    Поля:
        email: EmailField - email пользователя (опционально)
        role: CharField - роль пользователя (owner/admin/worker)
        phone: CharField - телефон (опционально)
        full_name: CharField - полное имя
        avatar: ImageField - аватар пользователя
        language: CharField - предпочитаемый язык (uz_cyrl/ru)
        can_write_to_owner: BooleanField - может ли писать владельцу
        can_create_workers: BooleanField - может ли создавать работников
        can_see_other_workers: BooleanField - может ли видеть других работников
        created_at: DateTimeField - время создания аккаунта
        updated_at: DateTimeField - время последнего обновления

    Свойства:
        is_owner: bool - True если роль owner
        is_admin: bool - True если роль admin
        is_worker: bool - True если роль worker
        display_role: str - отображаемое название роли
    """

    class Role(models.TextChoices):
        """
        Роли пользователей в системе.

        SUPERADMIN: платформенный супер-администратор - управляет компаниями,
                    не привязан к компании, не видит бизнес-данные.
        OWNER: владелец бизнеса - полный доступ ко всем данным своей компании
        ADMIN: администратор - управление складом и работниками своей компании
        MANAGER: менеджер - просмотр клиентов, заказов и производства
                 (только чтение, без финансовых сумм); без доступа к финансам
                 и настройкам. Создание/изменение записей - только
                 owner/admin (а для производства - ещё и worker).
        WORKER: работник - ограниченный доступ для выполнения задач
        """
        SUPERADMIN = 'superadmin', 'Super Administrator'
        OWNER = 'owner', 'Egasi'
        ADMIN = 'admin', 'Administrator'
        MANAGER = 'manager', 'Menejer'
        WORKER = 'worker', 'Ishchi'

    class Language(models.TextChoices):
        """
        Поддерживаемые языки интерфейса.

        UZBEK: узбекский (кириллица) - основной язык
        RUSSIAN: русский - дополнительный язык
        KYRGYZ: кыргызский - дополнительный язык
        """
        UZBEK = 'uz_cyrl', 'Ўзбекча'
        RUSSIAN = 'ru', 'Русский'
        KYRGYZ = 'ky', 'Кыргызча'

    class Status(models.TextChoices):
        """
        Кадровый статус сотрудника (НЕ путать с is_active — блокировкой входа).

        ACTIVE: работает
        ON_LEAVE: в отпуске
        SUSPENDED: временно отстранён
        """
        ACTIVE = 'active', 'Faol'
        ON_LEAVE = 'on_leave', 'Taʼtilda'
        SUSPENDED = 'suspended', 'Toʼxtatilgan'

    # Компания (арендатор). None только для платформенного супер-администратора.
    company = models.ForeignKey(
        'companies.Company',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='users', verbose_name='Компания'
    )

    # Основные поля профиля
    email = models.EmailField(blank=True, default='', verbose_name='Эл. почта')
    role = models.CharField(max_length=12, choices=Role.choices, default=Role.WORKER, db_index=True, verbose_name='Роль')
    phone = models.CharField(max_length=20, blank=True, default='', verbose_name='Телефон')
    full_name = models.CharField(max_length=255, blank=True, default='', verbose_name='Полное имя')
    avatar = models.ImageField(upload_to='avatars/', blank=True, default='', validators=[validate_file_size], verbose_name='Фотография')
    language = models.CharField(max_length=10, choices=Language.choices, default=Language.UZBEK, verbose_name='Язык интерфейса')

    # Расширенный профиль сотрудника
    position = models.CharField(max_length=255, blank=True, default='', verbose_name='Должность')      # должность
    department = models.CharField(max_length=255, blank=True, default='', verbose_name='Отдел')    # отдел
    birth_date = models.DateField(null=True, blank=True, verbose_name='Дата рождения')                     # дата рождения (опц.)
    hire_date = models.DateField(null=True, blank=True, verbose_name='Дата приёма')                      # дата найма
    bio = models.TextField(blank=True, default='', verbose_name='О сотруднике')                          # о себе
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True, verbose_name='Статус'
    )
    last_activity = models.DateTimeField(null=True, blank=True, verbose_name='Последняя активность')              # последняя активность

    # Профессиональные навыки (каталог навыков компании)
    skills = models.ManyToManyField('Skill', blank=True, related_name='employees', verbose_name='Навыки')

    # Дополнительные права для администраторов
    can_write_to_owner = models.BooleanField(default=False, verbose_name='Может писать владельцу')
    can_create_workers = models.BooleanField(default=False, verbose_name='Может создавать работников')
    can_see_other_workers = models.BooleanField(default=False, verbose_name='Видит других работников')

    # True, если аккаунт заблокирован ИНДИВИДУАЛЬНО владельцем (toggle_active),
    # а не каскадом от блокировки компании. При разблокировке компании такие
    # сотрудники НЕ должны молча восстанавливаться. Не путать с is_active
    # (общий флаг «вход разрешён»).
    blocked_by_owner = models.BooleanField(default=False, verbose_name='Заблокирован владельцем')

    # Временные метки
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Создано')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Обновлено')

    # Кастомный менеджер
    objects = UserManager()

    class Meta:
        verbose_name = 'Пользователь'
        verbose_name_plural = 'Пользователи'
        ordering = ['-created_at']
        constraints = [
            # Ровно один владелец на компанию (а не один на всю систему).
            models.UniqueConstraint(
                fields=['company'],
                condition=models.Q(role='owner'),
                name='accounts_single_owner_per_company',
            ),
        ]

    def __str__(self):
        """
        Строковое представление пользователя.

        Возвращает полное имя если оно указано, иначе username.
        """
        return self.full_name or self.username

    @property
    def is_superadmin(self):
        """
        Проверяет, является ли пользователь платформенным супер-администратором.

        Возвращает:
            bool - True если role == 'superadmin'
        """
        return self.role == self.Role.SUPERADMIN

    @property
    def is_owner(self):
        """
        Проверяет, является ли пользователь владельцем.

        Возвращает:
            bool - True если role == 'owner'
        """
        return self.role == self.Role.OWNER

    @property
    def is_admin(self):
        """
        Проверяет, является ли пользователь администратором.

        Возвращает:
            bool - True если role == 'admin'
        """
        return self.role == self.Role.ADMIN

    @property
    def is_worker(self):
        """
        Проверяет, является ли пользователь работником.

        Возвращает:
            bool - True если role == 'worker'
        """
        return self.role == self.Role.WORKER

    @property
    def is_manager(self):
        """
        Проверяет, является ли пользователь менеджером.

        Менеджер видит клиентов, заказы и производство (только чтение),
        но не имеет доступа к финансам и настройкам.

        Возвращает:
            bool - True если role == 'manager'
        """
        return self.role == self.Role.MANAGER

    @property
    def display_role(self):
        """
        Возвращает отображаемое название роли.

        Возвращает:
            str - человекочитаемое название роли на текущем языке
        """
        return dict(self.Role.choices).get(self.role, self.role)


class PushSubscription(TimestampedModel):
    """
    Web Push subscription для VAPID push-уведомлений.

    Хранит подписку браузера, полученную через Push API.
    Привязана к пользователю и компании для изоляции.
    """
    company = models.ForeignKey(
        'companies.Company', on_delete=models.CASCADE, related_name='push_subscriptions',
        null=True, blank=True, verbose_name='Компания'
    )
    user = models.ForeignKey(
        'accounts.User', on_delete=models.CASCADE, related_name='push_subscriptions', verbose_name='Пользователь'
    )
    endpoint = models.URLField(max_length=500, verbose_name='Адрес подписки')
    p256dh_key = models.CharField('P256DH ключ', max_length=255)
    auth_key = models.CharField('Auth ключ', max_length=255)
    user_agent = models.CharField(max_length=500, blank=True, default='', verbose_name='Устройство')
    is_active = models.BooleanField(default=True, verbose_name='Активен')

    class Meta:
        verbose_name = 'Push подписка'
        verbose_name_plural = 'Push подписки'
        ordering = ['-created_at']

    def __str__(self):
        return f'Push sub {self.user_id} ({self.company_id})'


class AccessKey(TimestampedModel):
    """
    Код-приглашение (Access Key) для активации аккаунта сотрудника.

    Публичной регистрации нет. Владелец (или супер-администратор) создаёт
    сотрудника, система генерирует уникальный одноразовый Access Key. Сотрудник
    вводит его при первом входе — аккаунт активируется, сотрудник задаёт пароль
    и входит; ключ помечается использованным.

    Ключ можно перевыпустить (regenerate — старый отзывается, создаётся новый),
    отозвать (revoke) и задать срок действия (expires_at). Одноразовость: после
    использования статус становится USED и повторно ключ не сработает.

    ИЗОЛЯЦИЯ: у ключа есть company — та же, что у сотрудника. Выборки в API и
    админке фильтруются по компании; сотрудник одной компании не может выпустить
    или увидеть ключи другой.
    """
    class Status(models.TextChoices):
        ACTIVE = 'active', 'Активен'
        USED = 'used', 'Использован'
        REVOKED = 'revoked', 'Отозван'

    company = models.ForeignKey(
        'companies.Company', on_delete=models.CASCADE, related_name='access_keys',
        verbose_name='Компания',
    )
    user = models.ForeignKey(
        'accounts.User', on_delete=models.CASCADE, related_name='access_keys',
        verbose_name='Сотрудник',
    )
    key = models.CharField(
        'Код доступа', max_length=32, unique=True, db_index=True,
        default=generate_access_key_code,
    )
    status = models.CharField(
        'Статус', max_length=10, choices=Status.choices, default=Status.ACTIVE, db_index=True,
    )
    expires_at = models.DateTimeField('Действует до', null=True, blank=True)
    used_at = models.DateTimeField('Использован', null=True, blank=True)
    created_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='issued_access_keys', verbose_name='Кем выдан',
    )

    class Meta:
        verbose_name = 'Код доступа'
        verbose_name_plural = 'Коды доступа (Access Key)'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['company', 'status']),
            models.Index(fields=['user', 'status']),
        ]

    def __str__(self):
        return f'{self.key} → {self.user_id} ({self.effective_status})'

    @property
    def is_expired(self):
        """Истёк ли срок действия ключа."""
        return bool(self.expires_at and timezone.now() > self.expires_at)

    @property
    def is_redeemable(self):
        """Можно ли активировать ключ прямо сейчас."""
        return self.status == self.Status.ACTIVE and not self.is_expired

    @property
    def effective_status(self):
        """Статус с учётом срока действия (active → expired, если срок вышел)."""
        if self.status == self.Status.ACTIVE and self.is_expired:
            return 'expired'
        return self.status


class SetupGate(models.Model):
    """
    Заглушка-блокировка первичной настройки системы (единственная запись).

    POST /setup/owner/ проверяет существование супер-администратора и создаёт
    его. Два параллельных запроса с разными username оба могли пройти проверку
    «суперадмина ещё нет» до того, как любой из них закоммитится, — и в системе
    появлялось два суперадмина. Здесь единственная строка (pk=1) берётся в
    SELECT ... FOR UPDATE: второй запрос ждёт коммита первого, после чего видит
    уже созданного суперадмина и получает 403.
    """
    id = models.PositiveIntegerField(primary_key=True, default=1, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Создана')

    class Meta:
        verbose_name = 'Заглушка первичной настройки'
        verbose_name_plural = 'Заглушки первичной настройки'

    def __str__(self):
        return 'Setup gate'
