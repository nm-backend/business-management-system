# SkladPro — локальный dev-сервер

## Как запустить

1. **Установить зависимости** (если не сделано):
   ```bash
   cd /c/Users/User/Documents/GitHub/business-management-system
   pip install -r requirements.txt
   ```

2. **Скопировать переменные окружения** (из основного чекаута):
   ```bash
   # Настройки уже есть в skladpro/dev_sqlite_settings.py
   # Он подтягивает базовые настройки из skladpro/settings/base.py
   # База данных: dev_preview.sqlite3 (уже готова)
   ```

3. **Запустить сервер**:
   ```bash
   python manage.py runserver 8081 --settings=skladpro.dev_sqlite_settings
   ```

   Либо с записью лога:
   ```bash
   python manage.py runserver 8081 --settings=skladpro.dev_sqlite_settings > .freebuff/preview-{thread}.log 2>&1 &
   ```

## Тестовые учётные записи (пароль: `test1234`)

| Пользователь | Роль | Компания |
|---|---|---|
| `superadmin` | Суперадмин (платформа) | — |
| `owner` | Владелец бизнеса | SkladPro Test |
| `admin` | Администратор | SkladPro Test |
| `worker` | Работник | SkladPro Test |

## Формат лога

Сервер пишет лог в `.freebuff/preview-*.log`. Содержит:
- Django autoreload watcher
- Daphne HTTP/WSGI endpoint
- Запросы и ошибки (через django.request логгер)

## Примечания

- Dev-настройки: `skladpro/dev_sqlite_settings.py`
- Пароли хешируются MD5 (для скорости в dev — `PASSWORD_HASHERS` в dev-настройках)
- База `dev_preview.sqlite3` уже содержит тестовые данные
- Static files: `python manage.py collectstatic` не нужен в dev (Django сам раздаёт)
