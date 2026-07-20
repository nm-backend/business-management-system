"""
Сервис двухэтапного подтверждения (2FA) на основе TOTP.

Вся логика 2FA собрана здесь, чтобы API, админка и тесты шли одним путём.
Под капотом — django-otp: TOTPDevice для кодов из приложения-аутентификатора
и StaticDevice для одноразовых резервных кодов.

МОДЕЛЬ УГРОЗ (что реально защищает и что нет):

  Защищает от: входа по украденному/подобранному паролю. Пароля недостаточно —
  нужен код с устройства сотрудника.

  НЕ защищает от: чтения базы данных. django-otp хранит секрет TOTP (поле key)
  и резервные коды в открытом виде. Тот, кто прочитал БД, может генерировать
  валидные коды. Хешировать резервные коды, оставив секрет TOTP открытым, было
  бы самообманом: секрет — более ценная цель. Реальная защита на этом уровне —
  шифрование БД/тома, а не хеширование на уровне приложения.

  Повторное использование кода невозможно: TOTPDevice.verify_token принимает
  только шаги строго новее last_t. Перехваченный код нельзя применить второй раз.

  Перебор ограничен: ThrottlingMixin django-otp даёт экспоненциальную задержку
  после неудачных попыток, поверх этого стоит DRF-троттлинг scope 'two_factor'.
"""
from base64 import b32encode, b64encode
from io import BytesIO
from os import urandom

from django.conf import settings
from django.db import transaction
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

# Имена устройств: у сотрудника не больше одного TOTP и одного набора резервных кодов.
TOTP_DEVICE_NAME = 'default'
RECOVERY_DEVICE_NAME = 'recovery'

# Результаты проверки кода.
VERIFY_TOTP = 'totp'
VERIFY_RECOVERY = 'recovery'


def _recovery_code():
    """
    16 символов base32 = 80 бит энтропии.

    Собственная генерация вместо StaticToken.random_token() (8 символов, 40 бит):
    резервный код полностью заменяет второй фактор, поэтому его стойкость должна
    быть сопоставима с паролем, а не с 6-значным TOTP.
    """
    return b32encode(urandom(10)).decode('ascii').lower()


def get_totp_device(user, *, confirmed=None):
    """Возвращает TOTP-устройство пользователя или None."""
    qs = TOTPDevice.objects.filter(user=user, name=TOTP_DEVICE_NAME)
    if confirmed is not None:
        qs = qs.filter(confirmed=confirmed)
    return qs.first()


def has_two_factor(user):
    """True, если у пользователя включено (подтверждено) 2FA."""
    if not getattr(user, 'is_authenticated', False):
        return False
    return TOTPDevice.objects.filter(
        user=user, name=TOTP_DEVICE_NAME, confirmed=True,
    ).exists()


def recovery_codes_left(user):
    """Сколько неиспользованных резервных кодов осталось."""
    device = StaticDevice.objects.filter(user=user, name=RECOVERY_DEVICE_NAME).first()
    return device.token_set.count() if device else 0


@transaction.atomic
def begin_setup(user):
    """
    Начинает подключение 2FA: создаёт НЕподтверждённое TOTP-устройство.

    Прежняя незавершённая попытка удаляется — иначе пользователь, начавший
    настройку дважды, получил бы QR-код от одного секрета, а подтверждал другой.

    Уже включённое 2FA не перезаписывается: перепривязка возможна только после
    явного отключения (с паролем и кодом). Иначе угнанная сессия молча
    привязала бы устройство злоумышленника.
    """
    if has_two_factor(user):
        raise ValueError('two_factor_already_enabled')

    TOTPDevice.objects.filter(user=user, name=TOTP_DEVICE_NAME, confirmed=False).delete()
    return TOTPDevice.objects.create(user=user, name=TOTP_DEVICE_NAME, confirmed=False)


@transaction.atomic
def confirm_setup(user, code):
    """
    Завершает подключение 2FA.

    Возвращает список резервных кодов (показывается ОДИН раз) или None,
    если код неверный.
    """
    device = get_totp_device(user, confirmed=False)
    if device is None or not device.verify_token(code):
        return None

    device.confirmed = True
    device.save(update_fields=['confirmed'])
    return _issue_recovery_codes(user)


@transaction.atomic
def regenerate_recovery_codes(user):
    """Перевыпускает резервные коды: старые перестают действовать немедленно."""
    return _issue_recovery_codes(user)


def _issue_recovery_codes(user):
    device, _ = StaticDevice.objects.get_or_create(user=user, name=RECOVERY_DEVICE_NAME)
    device.token_set.all().delete()
    count = getattr(settings, 'TWO_FACTOR_RECOVERY_CODE_COUNT', 10)
    codes = [_recovery_code() for _ in range(count)]
    StaticToken.objects.bulk_create(
        [StaticToken(device=device, token=code) for code in codes]
    )
    return codes


def verify_code(user, code):
    """
    Проверяет код второго фактора.

    Возвращает VERIFY_TOTP, VERIFY_RECOVERY или None.
    Резервный код после использования удаляется (одноразовый).

    Код направляется ровно в одно устройство по его форме: 6 цифр — TOTP,
    остальное — резервный код. Иначе каждая попытка входа резервным кодом
    засчитывалась бы TOTP-устройству как неудача и его счётчик задержки рос бы
    без реальной атаки (и наоборот).
    """
    code = (code or '').strip().replace(' ', '').replace('-', '')
    if not code:
        return None

    if code.isdigit() and len(code) == 6:
        device = get_totp_device(user, confirmed=True)
        return VERIFY_TOTP if device is not None and device.verify_token(code) else None

    recovery = StaticDevice.objects.filter(user=user, name=RECOVERY_DEVICE_NAME).first()
    if recovery is not None and recovery.verify_token(code.lower()):
        return VERIFY_RECOVERY

    return None


@transaction.atomic
def disable(user):
    """Полностью отключает 2FA: удаляет TOTP-устройство и резервные коды."""
    TOTPDevice.objects.filter(user=user, name=TOTP_DEVICE_NAME).delete()
    StaticDevice.objects.filter(user=user, name=RECOVERY_DEVICE_NAME).delete()


def provisioning_uri(device):
    """otpauth://-ссылка для приложения-аутентификатора."""
    return device.config_url


def qr_code_data_uri(device):
    """
    QR-код как data:image/png;base64 — фронтенд вставляет его в <img src>.

    Картинка генерируется на сервере: отдавать секрет во внешний
    QR-сервис нельзя, это полная компрометация второго фактора.
    """
    import qrcode

    img = qrcode.make(provisioning_uri(device))
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    encoded = b64encode(buffer.getvalue()).decode('ascii')
    return f'data:image/png;base64,{encoded}'
