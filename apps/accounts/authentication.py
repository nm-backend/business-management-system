"""
Кастомная JWT-аутентификация с отметкой последней активности.

Фронтенд — SPA на JWT: Django SessionMiddleware не видит пользователя на
API-запросах (сессии нет), поэтому «последнюю активность» нельзя надёжно
обновлять обычным middleware. Мы делаем это в слое аутентификации DRF, который
срабатывает на КАЖДОМ аутентифицированном API-запросе.

Запись троттлится (не чаще раза в ACTIVITY_THROTTLE), а обновление идёт через
queryset.update(), чтобы не трогать auto_now-поле updated_at и не плодить
лишние записи в БД на каждый запрос.
"""
from datetime import timedelta

from django.utils import timezone
from rest_framework_simplejwt.authentication import JWTAuthentication

ACTIVITY_THROTTLE = timedelta(minutes=5)


class ActivityJWTAuthentication(JWTAuthentication):
    """JWTAuthentication, дополнительно отмечающая last_activity пользователя."""

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
