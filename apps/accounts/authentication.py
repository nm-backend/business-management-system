"""
Кастомная JWT-аутентификация с отметкой последней активности.

Фронтенд — SPA на JWT: Django SessionMiddleware не видит пользователя на
API-запросах (сессии нет), поэтому «последнюю активность» нельзя надёжно
обновлять обычным middleware. Мы делаем это в слое аутентификации DRF, который
срабатывает на КАЖДОМ аутентифицированном API-запросе.

Запись троттлится (не чаще раза в ACTIVITY_THROTTLE), а обновление идёт через
queryset.update(), чтобы не трогать auto_now-поле updated_at и не плодить
лишние записи в БД на каждый запрос.

Также подгружается компания пользователя (select_related): её статус подписки
проверяется на каждом запросе (SubscriptionAccessPermission), и без префетча
это был бы отдельный запрос к БД на каждый API-вызов.
"""
from datetime import timedelta

from django.utils import timezone
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework_simplejwt.authentication import JWTAuthentication

ACTIVITY_THROTTLE = timedelta(minutes=5)


class ActivityJWTAuthentication(JWTAuthentication):
    """JWTAuthentication, дополнительно отмечающая last_activity пользователя."""

    def get_user(self, validated_token):
        """
        Загружает пользователя вместе с компанией (select_related).

        user.company читается на каждом запросе — статус подписки
        (SubscriptionAccessPermission), company_name в сериализаторах, ключ
        изоляции. Без select_related это был бы отдельный запрос к БД на
        каждый API-вызов.
        """
        from rest_framework_simplejwt.exceptions import (
            AuthenticationFailed, InvalidToken, TokenError,
        )
        from rest_framework_simplejwt.settings import api_settings

        try:
            user_id = validated_token[api_settings.USER_ID_CLAIM]
        except KeyError:
            raise InvalidToken('Token contained no recognizable user identification')

        try:
            user = self.user_model.objects.select_related('company').get(
                **{api_settings.USER_ID_FIELD: user_id},
            )
        except self.user_model.DoesNotExist:
            raise AuthenticationFailed('User not found', code='user_not_found')

        if not user.is_active:
            raise AuthenticationFailed('User is inactive', code='user_inactive')

        return user

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is not None:
            user, _token = result
            self._touch_last_activity(user)
        return result

    @staticmethod
    def _touch_last_activity(user):
        now = timezone.now()
        last = getattr(user, 'last_activity', None)
        if last is not None and (now - last) < ACTIVITY_THROTTLE:
            return
        # update() минует auto_now (updated_at) и хеширование — дёшево.
        type(user).objects.filter(pk=user.pk).update(last_activity=now)
        user.last_activity = now  # чтобы значение было актуальным в этом запросе
        # Последняя активность компании — для dashboard супер-администратора.
        if user.company_id is not None:
            from apps.companies.models import Company
            Company.objects.filter(pk=user.company_id).update(last_activity=now)


class ActivityJWTScheme(OpenApiAuthenticationExtension):
    """
    Описывает ActivityJWTAuthentication для OpenAPI (Bearer JWT).

    Без этого расширения drf_spectacular не знает, как задокументировать наш
    кастомный класс аутентификации, и на КАЖДЫЙ view сыплет W001
    «could not resolve authenticator». Регистрация убирает эти предупреждения и
    показывает в Swagger корректную схему Authorization: Bearer <token>.
    """
    target_class = 'apps.accounts.authentication.ActivityJWTAuthentication'
    name = 'jwtAuth'

    def get_security_definition(self, auto_schema):
        return {'type': 'http', 'scheme': 'bearer', 'bearerFormat': 'JWT'}
