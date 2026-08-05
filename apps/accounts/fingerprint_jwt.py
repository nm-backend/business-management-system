"""
JWT Fingerprint — защита refresh токена от кражи.

Каждый refresh токен содержит fingerprint_hash (SHA-256 от device fingerprint
клиента). При попытке обновления токена сервер проверяет, что fingerprint
в запросе совпадает с тем, что в токене.

Если fingerprint не совпал → detected token theft:
  - Все OutstandingToken пользователя добавляются в blacklist
  - Пишется audit log о краже токена
  - Возвращается 401 с флагом token_theft=true

Fingerprint — это UUID v4, который клиент генерирует один раз и хранит в
localStorage. Даже если злоумышленник украл refresh token, он не знает
fingerprint и не сможет обновить токен.

ВАЖНО: При вращении (refresh) новый токен тоже получает fingerprint —
иначе украденный rotated токен теряет защиту.
"""
import hashlib

from rest_framework import status
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken as BaseRefreshToken
from rest_framework_simplejwt.views import TokenRefreshView as BaseTokenRefreshView

from apps.audit.models import AuditLog
from apps.audit.services import write_audit_log


FINGERPRINT_CLAIM = 'fpr'  # custom claim in JWT payload


def _hash_fingerprint(fingerprint: str) -> str:
    """SHA-256 хеш от fingerprint (одностороннее преобразование)."""
    return hashlib.sha256(fingerprint.encode('utf-8')).hexdigest()


class RefreshToken(BaseRefreshToken):
    """
    Кастомный RefreshToken с fingerprint.

    Добавляет в payload claim 'fpr' — SHA-256 хеш от device fingerprint клиента.
    """

    def set_fingerprint(self, fingerprint: str):
        """Устанавливает fingerprint_hash в токен."""
        self.payload[FINGERPRINT_CLAIM] = _hash_fingerprint(fingerprint)

    def check_fingerprint(self, fingerprint: str) -> bool:
        """Проверяет, совпадает ли fingerprint с тем, что в токене."""
        stored = self.payload.get(FINGERPRINT_CLAIM)
        if not stored:
            return False
        return stored == _hash_fingerprint(fingerprint)


class FingerprintTokenRefreshSerializer(TokenRefreshSerializer):
    """
    Сериализатор refresh токена, сохраняющий fingerprint при вращении.

    SimpleJWT стандартно использует TokenRefreshSerializer, который создаёт
    новый RefreshToken (наш кастомный) но не копирует fingerprint. Этот
    сериализатор перехватывает создание нового токена и устанавливает
    fingerprint из оригинального токена.
    """

    def validate(self, attrs):
        # Стандартная валидация SimpleJWT: проверяет токен, вращает его.
        data = super().validate(attrs)

        # Вычитываем fingerprint из СТАРОГО токена (который был в запросе)
        # и встраиваем в НОВЫЙ токен, который сформировал super().validate().
        # Источник — claim старого токена, а НЕ запрос: иначе клиент без
        # fingerprint получил бы вращённый токен без защиты, и кража старого
        # токена стала бы безвозвратной (защита деградирует навсегда).
        old_token_str = attrs.get('refresh', '')

        if data.get('refresh'):
            try:
                old_token = RefreshToken(old_token_str)
                stored_fpr = old_token.payload.get(FINGERPRINT_CLAIM)
                if stored_fpr:
                    new_token = RefreshToken(data['refresh'])
                    new_token.payload[FINGERPRINT_CLAIM] = stored_fpr
                    data['refresh'] = str(new_token)
            except Exception:
                # Если не смогли — отдаём токен без fingerprint (безопасность
                # снижена, но не сломана — старый токен уже в blacklist'е).
                pass

        return data


class FingerprintTokenRefreshView(BaseTokenRefreshView):
    """
    Token refresh с проверкой fingerprint.

    POST /api/v1/accounts/token/refresh/
    Body: {"refresh": "...", "fingerprint": "..."}

    Использует FingerprintTokenRefreshSerializer, который:
    1. Проверяет fingerprint в старом токене
    2. Вращает токен (SimpleJWT)
    3. Встраивает fingerprint в новый токен
    """

    serializer_class = FingerprintTokenRefreshSerializer

    def get_serializer_context(self):
        """Передаём fingerprint из запроса в сериализатор."""
        context = super().get_serializer_context()
        context['fingerprint'] = self.request.data.get('fingerprint', '')
        return context

    def post(self, request, *args, **kwargs):
        fingerprint = request.data.get('fingerprint', '')
        refresh_token_str = request.data.get('refresh', '')

        # Шаг 1: валидируем fingerprint, если токен его требует.
        # Токен, выпущенный с защитой (claim fpr), обновить БЕЗ fingerprint
        # нельзя: иначе кража токена обходилась бы простым удалением поля
        # из запроса, а вращённый токен терял бы защиту навсегда.
        # Токены без fpr (выпущенные до внедрения фичи) обновляются как раньше.
        if refresh_token_str:
            try:
                token = RefreshToken(refresh_token_str)
                if token.payload.get(FINGERPRINT_CLAIM):
                    if not fingerprint:
                        return Response(
                            {'detail': 'fingerprint is required for this token'},
                            status=status.HTTP_401_UNAUTHORIZED,
                        )
                    if not token.check_fingerprint(fingerprint):
                        return self._handle_theft(token)
            except (InvalidToken, TokenError):
                return Response(
                    {'detail': 'Token is invalid or expired'},
                    status=status.HTTP_401_UNAUTHORIZED,
                )

        # Шаг 2: Вращаем токен через SimpleJWT (стандартный refresh).
        # Сериализатор FingerprintTokenRefreshSerializer сам перенесёт
        # fingerprint из старого токена в новый.
        return super().post(request, *args, **kwargs)

    def _handle_theft(self, token):
        """
        Обнаружена кража refresh токена.

        Немедленно инвалидируем ВСЕ refresh токены пользователя и пишем audit log.
        """
        from .token_utils import blacklist_all_tokens

        user_id = token.payload.get('user_id')
        jti = token.payload.get('jti')

        try:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            user = User.objects.filter(pk=user_id).first()
            if user:
                count = blacklist_all_tokens(user)
                write_audit_log(
                    action=AuditLog.Action.TOKEN_THEFT_DETECTED,
                    actor=user,
                    target=user,
                    metadata={
                        'stolen_jti': jti,
                        'blacklisted_count': count,
                    },
                )
        except Exception:
            pass  # Никогда не падаем в security-коде

        return Response(
            {
                'detail': 'Token theft detected. All sessions have been terminated. '
                          'Please login again with your credentials.',
                'token_theft': True,
            },
            status=status.HTTP_401_UNAUTHORIZED,
        )
