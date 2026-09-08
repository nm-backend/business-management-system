"""
Активные сессии пользователя поверх штатного JWT-механизма.

Источник истины — simplejwt: OutstandingToken (выданные refresh-токены) и
BlacklistedToken (отозванные). Здесь только чтение этих таблиц и запись
метаданных устройства (UserSession), чтобы экран «Сеансларни бошқариш»
показывал понятные строки, а не идентификаторы.

Отзыв сессии = запись в blacklist. Никакой параллельной аутентификации.
"""
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken, OutstandingToken,
)

from .fingerprint_jwt import FINGERPRINT_CLAIM
from .models import UserSession


def client_ip(request):
    """IP клиента с учётом обратного прокси."""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR') or None


def record_session(user, refresh, request):
    """
    Запоминает устройство для только что выданного refresh-токена.

    Вызывается там же, где токен выдаётся (вход, активация по ключу, ротация).
    Ошибка записи метаданных не должна ломать вход, поэтому вызывающий код
    оборачивает вызов в try/except — сессия без описания устройства всё равно
    видна в списке (данные берутся из OutstandingToken).
    """
    jti = refresh.payload.get('jti')
    if not jti:
        return None
    return UserSession.objects.update_or_create(
        jti=jti,
        defaults={
            'user': user,
            'fingerprint_hash': refresh.payload.get(FINGERPRINT_CLAIM, '') or '',
            'user_agent': (request.META.get('HTTP_USER_AGENT') or '')[:400] if request else '',
            'ip_address': client_ip(request) if request else None,
            'last_used_at': timezone.now(),
        },
    )[0]


def active_sessions(user):
    """
    Живые сессии пользователя: выданные, не отозванные и не истёкшие.

    Именно OutstandingToken, а не UserSession: если метаданные почему-то не
    записались, сессия обязана остаться видимой — иначе пользователь не сможет
    её закрыть.
    """
    blacklisted = BlacklistedToken.objects.values_list('token_id', flat=True)
    return (
        OutstandingToken.objects
        .filter(user=user, expires_at__gt=timezone.now())
        .exclude(id__in=blacklisted)
        .order_by('-created_at')
    )


def revoke_session(user, jti):
    """
    Отзывает конкретную сессию пользователя.

    Возвращает True, если сессия найдена и отозвана. Чужие сессии не
    отзываются: выборка ограничена токенами этого пользователя.
    """
    token = OutstandingToken.objects.filter(user=user, jti=jti).first()
    if token is None:
        return False
    BlacklistedToken.objects.get_or_create(token=token)
    return True


def revoke_other_sessions(user, keep_fingerprint=''):
    """
    Отзывает все сессии, кроме текущей (её определяем по отпечатку устройства).

    Если отпечатка нет (старые клиенты его не присылали), отзываются все
    сессии — это осознанно: лучше потребовать повторный вход, чем оставить
    чужое устройство активным.
    """
    kept_jti = set()
    if keep_fingerprint:
        kept_jti = set(
            UserSession.objects
            .filter(user=user, fingerprint_hash=keep_fingerprint)
            .values_list('jti', flat=True)
        )

    revoked = 0
    for token in active_sessions(user):
        if token.jti in kept_jti:
            continue
        BlacklistedToken.objects.get_or_create(token=token)
        revoked += 1
    return revoked


def serialize_sessions(user, current_fingerprint=''):
    """Список сессий для API: устройство, адрес, даты и признак текущей."""
    meta = {
        item.jti: item
        for item in UserSession.objects.filter(user=user)
    }
    rows = []
    for token in active_sessions(user):
        info = meta.get(token.jti)
        rows.append({
            'jti': token.jti,
            'created_at': token.created_at,
            'expires_at': token.expires_at,
            'user_agent': info.user_agent if info else '',
            'ip_address': info.ip_address if info else None,
            'last_used_at': info.last_used_at if info else None,
            'is_current': bool(
                current_fingerprint
                and info
                and info.fingerprint_hash == current_fingerprint
            ),
        })
    return rows
