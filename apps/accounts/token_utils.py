"""
Инвалидация JWT-токенов пользователя (SimpleJWT Blacklist).

При смене/сбросе пароля, блокировке или отключении аккаунта все ранее
выданные refresh-токены пользователя должны перестать действовать — иначе
украденный refresh-токен продолжал бы генерировать access-токены до 7 дней
(классический сценарий «сбросить пароль, чтобы выгнать злоумышленника», не
срабатывал бы).

ОГОВОРКА (честно): блэклистятся refresh-токены. Уже выданные короткоживущие
access-токены (45 минут) остаются валидными до истечения — их SimpleJWT не
хранит и не отзывает. Это стандартное поведение JWT; окно компрометации
ограничено 45 минутами.
"""


def blacklist_all_tokens(user):
    """
    Добавляет в blacklist все outstanding refresh-токены пользователя.

    Возвращает число заблокированных токенов. Безопасно вызывать, даже если у
    пользователя не было токенов (вернёт 0).
    """
    try:
        from rest_framework_simplejwt.token_blacklist.models import (
            BlacklistedToken, OutstandingToken,
        )
    except Exception:
        # Приложение blacklist не установлено — отзывать нечего.
        return 0

    count = 0
    for token in OutstandingToken.objects.filter(user=user):
        _, created = BlacklistedToken.objects.get_or_create(token=token)
        if created:
            count += 1
    return count
