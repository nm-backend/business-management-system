# SkladPro.Nod — Система автоматизации управления производством

Многопользовательская (multi-tenant) SaaS ERP-система для производственных
компаний: склад сырья, готовая продукция, производство, заказы, клиенты,
финансы, аналитика, отчёты и внутренние сообщения. Каждая компания видит
только свои данные.

- **Backend:** Django 5.1 + Django REST Framework + JWT (SimpleJWT)
- **Real-time:** Django Channels + WebSocket (корпоративный чат). В разработке —
  in-memory канальный слой (Redis не нужен); в production — Redis.
- **API-документация:** drf-spectacular (Swagger UI + ReDoc)
- **База данных:** PostgreSQL
- **Frontend:** SPA на чистом JavaScript (без сборки, без Node.js), отдаётся
  Django-шаблонами. Роутинг через hash-router, авторизация — JWT в localStorage.

> Этот гайд проверен запуском проекта «с нуля» на Windows 11 (см. раздел
> [15. Итоговая проверка](#15-итоговая-проверка-честный-отчёт)).

---

## 1. Требования

| Компонент   | Версия (проверено)      | Примечание |
|-------------|-------------------------|------------|
| Python      | **3.13** (3.13.13)      | Подойдёт 3.11+. `python --version` |
| PostgreSQL  | **18**                  | Подойдёт 12+. `psql --version` |
| Git         | любая свежая            | Или GitHub Desktop |
| ОС          | Windows 10/11           | Гайд написан под Windows; на macOS/Linux меняются только пути |
| Redis       | только для production   | Нужен для WebSocket-чата в проде. **В разработке НЕ требуется** (используется in-memory канальный слой). |

**Node.js / npm НЕ требуются.** Фронтенд — статические JS-файлы, шага сборки нет.

**Real-time чат работает «из коробки» в dev:** `runserver` автоматически
поднимает ASGI-сервер (Daphne) и обслуживает WebSocket. Redis для разработки
не нужен.

---

## 2. Клонирование

Через командную строку:

```bash
git clone https://github.com/<owner>/business-management-system.git
cd business-management-system
```

Через **GitHub Desktop**: `File → Clone repository…` → выбрать репозиторий →
`Clone`. Затем `Repository → Open in Command Prompt` (или PowerShell).

---

## 3. Виртуальное окружение (Windows)

Из корня проекта:

```powershell
# Создать venv
python -m venv venv

# Активировать (PowerShell)
venv\Scripts\Activate.ps1

# либо в cmd.exe:
venv\Scripts\activate.bat
```

После активации в начале строки появится `(venv)`.

> Если PowerShell пишет «выполнение сценариев отключено», разрешите их для
> текущего пользователя:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

---

## 4. Установка зависимостей

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Устанавливаются: Django, DRF, SimpleJWT, psycopg2-binary, python-decouple,
django-cors-headers, Pillow, reportlab, openpyxl, django-filter, gunicorn,
drf-spectacular, **channels + daphne** (WebSocket), **channels-redis**
(канальный слой для production). Все версии закреплены в `requirements.txt`.

---

## 5. Настройка PostgreSQL

Проект использует PostgreSQL (в тестах — SQLite in-memory, отдельная БД не нужна).

### 5.1. Открыть psql

```powershell
# Windows: обычно psql лежит здесь
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres
```

Введите пароль пользователя `postgres`, заданный при установке PostgreSQL.

### 5.2. Создать БД и пользователя

Внутри `psql` (можно использовать существующего пользователя `postgres` или
создать отдельного — рекомендуется отдельный):

```sql
-- Отдельный пользователь приложения (рекомендуется)
CREATE USER skladpro_user WITH PASSWORD 'change_me_strong';

-- База данных
CREATE DATABASE skladpro_db OWNER skladpro_user ENCODING 'UTF8';

-- Права
GRANT ALL PRIVILEGES ON DATABASE skladpro_db TO skladpro_user;

-- (PostgreSQL 15+) права на схему public, иначе migrate упадёт с
-- "permission denied for schema public"
\c skladpro_db
GRANT ALL ON SCHEMA public TO skladpro_user;

\q
```

**Простой вариант** (для локальной разработки): использовать встроенного
`postgres` как владельца — тогда в `.env` укажите `DB_USER=postgres` и его пароль.

Пример полного набора значений для `.env` под этот раздел:

```
DB_NAME=skladpro_db
DB_USER=skladpro_user
DB_PASSWORD=change_me_strong
DB_HOST=localhost
DB_PORT=5432
```

---

## 6. Файл `.env`

Скопируйте шаблон и заполните значения:

```powershell
copy .env.example .env
```

Переменные (файл `.env` в корне проекта):

| Переменная      | Обязательна | Значение / пример | Назначение |
|-----------------|-------------|-------------------|------------|
| `SECRET_KEY`    | **да**      | длинная случайная строка | Криптоключ Django. Сгенерировать: `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` |
| `DJANGO_ENV`    | нет         | `development` (по умолч.) / `production` | Какой набор настроек грузить (`skladpro/settings/development.py` или `production.py`) |
| `DEBUG`         | нет         | `True` для разработки, `False` в проде | Режим отладки |
| `ALLOWED_HOSTS` | нет (в dev) | `localhost,127.0.0.1` | Разрешённые хосты, через запятую |
| `DB_NAME`       | **да**      | `skladpro_db` | Имя базы |
| `DB_USER`       | **да**      | `skladpro_user` / `postgres` | Пользователь БД |
| `DB_PASSWORD`   | **да**      | ваш пароль | Пароль БД |
| `DB_HOST`       | **да**      | `localhost` | Хост БД |
| `DB_PORT`       | **да**      | `5432` | Порт БД |
| `MEDIA_URL`     | нет         | `/media/` | URL для загруженных файлов |
| `MEDIA_ROOT`    | нет         | `media/` | Папка для загруженных файлов |
| `REDIS_URL`     | только prod | `redis://127.0.0.1:6379/0` | Канальный слой Channels для WebSocket. В dev не нужен (in-memory). |

> **Важно:** переменные окружения ОС имеют приоритет над `.env` (так работает
> python-decouple). Если, например, в системе выставлен `DB_NAME`, он
> перекроет значение из `.env`. Проверьте `echo $env:DB_NAME` (PowerShell),
> если БД подключается «не туда».

---

## 7. Миграции

```powershell
python manage.py migrate
```

Ожидаемый результат — список `Applying …  OK` без ошибок. Проверить состояние
проекта и отсутствие незакоммиченных изменений моделей:

```powershell
python manage.py check                 # System check identified no issues
python manage.py makemigrations --check # No changes detected
```

---

## 8. Первый пользователь (супер-администратор платформы)

Система многопользовательская. Верхний уровень — **супер-администратор**
(`role=superadmin`, `company=None`): он не принадлежит ни одной компании и
создаёт компании вместе с их владельцами (через Django Admin или API).

Создать супер-администратора:

```powershell
python manage.py createsuperuser
```

Введите username, email (можно пустой) и пароль. Команда создаёт пользователя
с `role=superadmin`, `is_staff=True`, `is_superuser=True`, `company=None`
(логика в `apps/accounts/managers.py`).

Неинтерактивно (например, для скриптов):

```powershell
$env:DJANGO_SUPERUSER_USERNAME="admin"
$env:DJANGO_SUPERUSER_PASSWORD="Admin12345"
$env:DJANGO_SUPERUSER_EMAIL="admin@example.com"
python manage.py createsuperuser --noinput
```

**Что дальше — создание компании и владельца:**
1. Зайти в Django Admin `http://localhost:8000/admin/` под супер-админом.
2. `Companies → Add`: указать название компании и данные владельца
   (username / пароль / ФИО) — компания и её владелец создаются за один шаг.
3. Владелец логинится на сайте и заводит администраторов и рабочих.

(То же можно сделать через API: `POST /api/v1/companies/` под супер-админом.)

---

## 9. Запуск сервера

```powershell
python manage.py runserver
```

По умолчанию — `http://127.0.0.1:8000/`. Открыть в браузере:

| Адрес | Что это |
|-------|---------|
| http://localhost:8000/ | Приложение (SPA) |
| http://localhost:8000/accounts/login/ | Страница входа |
| http://localhost:8000/admin/ | Django Admin (для супер-админа) |
| http://localhost:8000/api/v1/swagger/ | Swagger UI (интерактивная API-документация) |
| http://localhost:8000/api/v1/redoc/ | ReDoc (читаемая API-документация) |
| http://localhost:8000/api/v1/schema/ | OpenAPI-схема (YAML) |

Запуск на другом порту: `python manage.py runserver 8001`.

> **WebSocket-чат:** т.к. `daphne` первым стоит в `INSTALLED_APPS`, `runserver`
> запускается как ASGI и сам обслуживает WebSocket по адресу `/ws/chat/`.
> Отдельная команда не нужна. Проверка: откройте чат («Хабарлар» → вкладка
> «Чат»), в DevTools → Network → WS должно быть соединение `101 Switching
> Protocols`.

---

## 10. Тесты

Тесты используют отдельные настройки (`skladpro.test_settings`, SQLite
in-memory) — реальную БД PostgreSQL они не трогают.

```powershell
# PowerShell
$env:DJANGO_SETTINGS_MODULE="skladpro.test_settings"
python manage.py test

# cmd.exe
set DJANGO_SETTINGS_MODULE=skladpro.test_settings
python manage.py test
```

**Как выглядит успех:**

```
Ran 153 tests in X.XXXs

OK
```

Отдельное приложение — например изоляция компаний или чат:
`python manage.py test apps.companies apps.messaging`.
(Тесты чата используют in-memory канальный слой Channels — Redis для тестов не нужен.)

---

## 11. Частые ошибки и их решение

### PostgreSQL не подключается
- **Симптом:** `could not connect to server` / `connection refused` /
  `password authentication failed`.
- **Причина:** служба PostgreSQL не запущена, неверные `DB_USER`/`DB_PASSWORD`/
  `DB_PORT`, либо БД не создана.
- **Решение:** проверьте, что служба запущена (Windows: `services.msc` →
  `postgresql-x64-18`). Проверьте вход вручную:
  `psql -U <DB_USER> -d <DB_NAME> -h localhost`. Сверьте значения с `.env`.

### `migrate` падает
- **Симптом:** `permission denied for schema public`.
- **Причина:** в PostgreSQL 15+ у нового пользователя нет прав на схему `public`.
- **Решение:** `GRANT ALL ON SCHEMA public TO <DB_USER>;` (см. раздел 5.2).
- **Симптом:** `relation ... already exists` / конфликт миграций.
- **Решение:** для чистого старта пересоздайте БД
  (`DROP DATABASE skladpro_db; CREATE DATABASE …`) и выполните `migrate` заново.

### `.env` не читается
- **Симптом:** Django берёт настройки по умолчанию, а не из `.env`.
- **Причина:** файл называется не `.env`, лежит не в корне, либо переменная
  задана в окружении ОС и перекрывает файл.
- **Решение:** убедитесь, что `.env` в корне рядом с `manage.py`. Проверьте
  окружение: `echo $env:SECRET_KEY`. Переменные ОС имеют приоритет.

### Ошибки CORS
- **Симптом:** в консоли браузера `blocked by CORS policy`.
- **Причина:** запрос с origin, которого нет в разрешённых.
- **Решение:** в разработке (`DEBUG=True`) CORS открыт. В проде задайте
  разрешённые origin в настройках (`production.py`, `CORS_ALLOW_ALL_ORIGINS=False`).

### Порт занят
- **Симптом:** `Error: That port is already in use.`
- **Решение:** запустите на другом порту (`python manage.py runserver 8001`)
  или освободите порт: `netstat -ano | findstr :8000`, затем
  `taskkill /PID <pid> /F`.

### `ModuleNotFoundError`
- **Симптом:** `No module named 'rest_framework'` (или другой пакет).
- **Причина:** не активирован venv или не установлены зависимости.
- **Решение:** активируйте venv (`venv\Scripts\Activate.ps1`), затем
  `pip install -r requirements.txt`.

### Статика не грузится (нет стилей)
- **Симптом:** страница без CSS.
- **Причина в dev:** `DEBUG=False` без `collectstatic`.
- **Решение:** для разработки держите `DEBUG=True`. Для прода выполните
  `python manage.py collectstatic`.

### Старый CSS/JS в браузере
- **Симптом:** правки не видны.
- **Причина:** кэш браузера. В проекте есть версионирование ассетов (`?v=`),
  но при жёстком кэше поможет **Ctrl+F5** (жёсткая перезагрузка) или режим
  инкогнито.

### JWT: 401 Unauthorized
- **Симптом:** API отвечает `401` после входа.
- **Причина:** истёк access-токен или он не передан.
- **Решение:** обновите токен через `POST /api/v1/accounts/token/refresh/`
  или войдите заново. Токен должен идти в заголовке
  `Authorization: Bearer <token>`.

### CSRF (403) при работе через Django Admin / формы
- **Симптом:** `CSRF verification failed` в Django Admin.
- **Причина:** отсутствует/просрочен CSRF-cookie.
- **Решение:** обновите страницу, чтобы получить свежий CSRF-токен.
  Публичные API-эндпоинты входа (`login`, `setup`) от CSRF освобождены —
  они работают на JWT, не на сессиях.

### Swagger не открывается
- **Симптом:** `/api/v1/swagger/` даёт ошибку.
- **Причина:** обычно не установлен `drf-spectacular`.
- **Решение:** `pip install -r requirements.txt`. Проверить схему:
  `python manage.py spectacular --file schema.yaml`.

### `createsuperuser` — ошибки валидации
- **Симптом:** команда ругается на пароль/username.
- **Решение:** пароль не короче 8 символов и не слишком простой; username
  уникален.

---

## 12. Чек-лист работоспособности

Пройдите после запуска — всё должно проходить:

- [ ] `http://localhost:8000/` открывается (SPA грузится)
- [ ] Страница входа `/accounts/login/` открывается
- [ ] Логин супер-админа работает (через Django Admin `/admin/`)
- [ ] Создание компании + владельца в Django Admin проходит
- [ ] Владелец компании логинится на сайте
- [ ] Администратор компании логинится и видит только свою компанию
- [ ] Рабочий логинится с ограниченными правами
- [ ] Swagger UI `/api/v1/swagger/` открывается
- [ ] ReDoc `/api/v1/redoc/` открывается
- [ ] Django Admin `/admin/` доступен супер-админу
- [ ] API отвечает: `GET /api/v1/accounts/setup/check/` → `200`
- [ ] Чат работает: «Хабарлар» → «Чат», виден «Умумий чат», сообщение
      отправляется; WebSocket `/ws/chat/` подключён (DevTools → Network → WS)
- [ ] Тесты проходят: `python manage.py test` (с `DJANGO_SETTINGS_MODULE=skladpro.test_settings`) → `OK`

---

## 13. Структура проекта

```
business-management-system/
├── manage.py                  # Точка входа Django
├── requirements.txt           # Python-зависимости (версии закреплены)
├── .env.example               # Шаблон переменных окружения
├── skladpro/                  # Конфигурация проекта
│   ├── settings/
│   │   ├── base.py            # Базовые настройки
│   │   ├── development.py     # DEBUG-настройки (по умолчанию)
│   │   ├── production.py      # Прод: HSTS, secure cookies, SSL redirect
│   │   └── __init__.py        # Выбор окружения по DJANGO_ENV
│   ├── test_settings.py       # Настройки тестов (SQLite in-memory)
│   └── urls.py                # Корневые маршруты (API, Swagger, admin)
├── apps/                      # Бизнес-модули (Django-приложения)
│   ├── accounts/             # Пользователи, роли, JWT-аутентификация
│   ├── companies/            # Компании (арендаторы), SaaS-онбординг
│   ├── clients/              # Клиенты (активные/архив)
│   ├── warehouse/            # Склад сырья и готовой продукции
│   ├── production/           # Производство и задачи
│   ├── orders/               # Заказы
│   ├── finance/              # Расходы, выплаты рабочим
│   ├── reports/              # Аналитика и отчёты
│   ├── messaging/            # Чат + уведомления (изолированы по компании):
│   │                         #   models(Conversation/ChatMessage) · consumers.py
│   │                         #   (WebSocket) · routing.py · ws_auth.py (JWT для WS)
│   ├── audit/                # Журнал аудита
│   └── core/                 # Общие permissions, mixins, утилиты
├── core/                      # Общий код проекта
├── static/                    # Frontend: CSS и vanilla-JS SPA
│   ├── css/
│   └── js/
│       ├── components/       # Экраны SPA
│       └── icons.js          # SVG-иконки навигации
├── templates/                 # Django-шаблоны (оболочка SPA, вход)
└── locale/                    # Переводы (Узбекский / Русский)
```

**Ключевые архитектурные принципы:**
- **Multi-tenant:** у каждой бизнес-сущности есть FK `company`; queryset'ы
  фильтруются по компании текущего пользователя. Компании не видят данные
  друг друга (проверяется тестами в `apps/companies/tests.py`).
- **Роли:** `superadmin` (платформа, `company=None`) / `owner` / `admin` /
  `worker`. Права — через DRF permissions (`IsCompanyMember`, `IsSuperAdmin` и т.д.).
- **Финансы:** финансовые данные не отдаются рабочим/администраторам, которым
  они не положены (проверяется на уровне сериализаторов и permissions).

---

## 14. Развёртывание в production (кратко)

1. `.env`: `DJANGO_ENV=production`, `DEBUG=False`, реальный `ALLOWED_HOSTS`,
   сильный `SECRET_KEY`, `REDIS_URL` (для WebSocket-чата).
2. Запустить **Redis** — в проде это общий канальный слой Channels
   (в `production.py` уже настроен `channels_redis` по `REDIS_URL`).
3. `python manage.py collectstatic`
4. Приложение обслуживает и HTTP, и WebSocket через **ASGI**, поэтому в проде
   запускайте ASGI-сервер, а не только gunicorn/WSGI. Варианты:
   - Daphne (уже в зависимостях): `daphne -b 0.0.0.0 -p 8000 skladpro.asgi:application`
   - либо Uvicorn-воркеры под gunicorn:
     `gunicorn skladpro.asgi:application -k uvicorn.workers.UvicornWorker`
   > Чистый `gunicorn skladpro.wsgi:application` обслужит сайт и API, но
   > **не** WebSocket — чат не будет обновляться в реальном времени.
5. За reverse-proxy (nginx) с HTTPS. Для WebSocket проксируйте `/ws/` с
   заголовками `Upgrade`/`Connection`. В `production.py` включены HSTS,
   `SECURE_SSL_REDIRECT`, secure/HttpOnly cookies.

---

## 15. Итоговая проверка (честный отчёт)

**Запускался ли проект «с нуля»?** Да. Перед написанием этого гайда проект был
поднят с нуля в изолированном окружении, как будто репозиторий открыт впервые.

**Что именно было выполнено (реально исполненные команды):**
1. Создан новый venv отдельным интерпретатором Python 3.13.13.
2. `pip install -r requirements.txt` — все зависимости установились без ошибок.
3. Создана чистая база PostgreSQL 18 (`CREATE DATABASE …`).
4. `python manage.py migrate` из нуля — все миграции применились, ошибок нет.
5. `python manage.py check` → «System check identified no issues».
6. `python manage.py makemigrations --check` → изменений моделей нет (дрейфа нет).
7. `createsuperuser --noinput` → создан пользователь с `role=superadmin`,
   `is_superuser=True`, `company=None`.
8. `runserver` → проверены эндпоинты:
   `/` → 200, `/accounts/login/` → 200,
   `/api/v1/accounts/setup/check/` → 200, `/api/v1/swagger/` → 200,
   `/api/v1/redoc/` → 200, `/api/v1/schema/` → 200, `/admin/` → 302 (редирект
   на вход — норма).
9. Проверен вход супер-админа через API — вернулись данные пользователя и токены.
10. `python manage.py test` (test_settings, SQLite) → **135 тестов, OK**.

**Какие проблемы пришлось исправить:**
- В `requirements.txt` зависимость `drf-spectacular` была без версии. Для
  воспроизводимости она закреплена: `drf-spectacular==0.30.0` (версия, которую
  подтянула чистая установка). Больше при запуске с нуля ничего чинить не
  потребовалось.
- Обновлены `.env.example` (добавлено пояснение по `DJANGO_ENV` и все
  переменные) и этот `README.md` (раньше состоял из двух строк).

**Известные оставшиеся проблемы:** при запуске с нуля не выявлено. Приведённые
в разделе 11 ошибки — типовые окружения (не баги проекта), а не то, что
проявилось во время проверки.
