# SkladPro.Nod - Руководство по проекту

## Описание проекта

SkladPro.Nod - это система управления бизнесом для камнеобрабатывающего производства. Проект включает управление складом сырья и готовой продукции, отслеживание заказов, производство, клиентов и финансов.

**Основные возможности:**
- Управление пользователями с ролевой системой доступа (RBAC)
- Управление складом сырья (RawMaterial) и готовой продукции (FinishedProduct)
- Отслеживание движений склада (StockMovement)
- Рецепты производства (Recipe, RecipeItem)
- Полный аудит всех действий (AuditLog)
- Мультиязычность (узбекский кириллица, русский)
- JWT аутентификация

## Технологический стек

### Backend
- **Django 5.1.4** - веб-фреймворк
- **Django REST Framework** - API
- **PostgreSQL** - база данных
- **JWT (Simple JWT)** - аутентификация
- **python-decouple** - управление переменными окружения

### Frontend
- **Vanilla JavaScript** - SPA (Single Page Application)
- **CSS** - кастомные стили
- **Hash-based routing** - навигация

## Структура проекта

```
business-management-system/
├── apps/                          # Django приложения
│   ├── core/                      # Базовые модели и утилиты
│   │   ├── models.py              # TimestampedModel, SoftDeleteModel, Currency, ExchangeRate
│   │   ├── permissions.py         # Кастомные permissions для RBAC
│   │   ├── pagination.py          # Кастомная пагинация
│   │   └── utils.py               # Утилиты (deep_merge, get_locale, format_currency)
│   ├── accounts/                  # Управление пользователями
│   │   ├── models.py              # User модель с ролями
│   │   ├── managers.py            # UserManager
│   │   ├── serializers.py         # Сериализаторы для API
│   │   └── views.py               # API views (login, logout, profile, users)
│   ├── warehouse/                 # Управление складом
│   │   ├── models.py              # RawMaterial, FinishedProduct, StockMovement, Recipe
│   │   ├── serializers.py         # Сериализаторы склада
│   │   └── views.py               # API views склада
│   ├── audit/                    # Система аудита
│   │   ├── models.py              # AuditLog
│   │   ├── services.py            # Функции записи audit logs
│   │   └── views.py               # API views для audit logs
│   ├── orders/                    # Заглушка для заказов
│   ├── production/                # Заглушка для производства
│   ├── clients/                   # Заглушка для клиентов
│   ├── finance/                   # Заглушка для финансов
│   ├── messaging/                 # Заглушка для сообщений
│   └── reports/                   # Заглушка для отчетов
├── skladpro/                      # Настройки Django
│   ├── settings/
│   │   ├── base.py                # Общие настройки
│   │   ├── development.py         # Настройки для разработки
│   │   └── production.py          # Настройки для продакшена
│   ├── urls.py                    # Корневые URL
│   ├── wsgi.py                    # WSGI конфигурация
│   └── asgi.py                    # ASGI конфигурация
├── static/                        # Статические файлы
│   ├── css/                       # Стили
│   │   ├── base.css               # Базовые стили
│   │   └── style.css              # Дополнительные стили
│   └── js/                        # JavaScript
│       ├── api.js                 # API клиент (JWT токены)
│       ├── i18n.js                # Менеджер переводов
│       ├── router.js              # Роутер для SPA
│       ├── app.js                 # Главный файл приложения
│       └── components/            # Компоненты страниц
│           ├── dashboard.js       # Дашборд
│           ├── warehouse.js       # Склад сырья
│           └── finished_products.js # Готовая продукция
├── templates/                     # HTML шаблоны
│   ├── base.html                 # Базовый шаблон
│   ├── index.html                # Главный шаблон с навигацией
│   ├── accounts/                 # Шаблоны авторизации
│   └── components/               # Компоненты шаблонов
├── locale/                        # Файлы переводов
│   ├── uz_cyrl.json             # Узбекский (кириллица)
│   └── ru.json                  # Русский
├── .env                           # Переменные окружения
├── manage.py                      # Django management commands
└── PROJECT_GUIDE.md              # Этот файл
```

## Ролевая система доступа (RBAC)

Проект использует три роли пользователей:

### Owner (Владелец)
- Полный доступ ко всем функциям системы
- Может создавать и управлять администраторами и работниками
- Имеет доступ к финансовым данным (цены, себестоимость)
- Может просматривать все audit logs

### Admin (Администратор)
- Управление складом (сырье и готовая продукция)
- Может создавать работников (при наличии разрешения `can_create_workers`)
- Не имеет доступа к финансовым данным
- Не может управлять другими администраторами

### Worker (Работник)
- Ограниченный доступ к складу (только просмотр)
- Не может управлять пользователями
- Не имеет доступа к финансовым данным

## API Endpoints

### Аутентификация (`/api/v1/accounts/`)
- `POST /setup/check/` - Проверка наличия владельца
- `POST /setup/owner/` - Создание владельца (первичная настройка)
- `POST /login/` - Вход в систему
- `POST /logout/` - Выход из системы
- `GET /me/` - Текущий пользователь
- `PATCH /me/` - Обновление профиля
- `POST /me/change-password/` - Смена пароля
- `POST /me/language/` - Смена языка

### Управление пользователями (`/api/v1/accounts/users/`)
- `GET /` - Список пользователей (фильтруется по роли)
- `POST /` - Создание пользователя (owner/admin)
- `GET /{id}/` - Детали пользователя
- `PATCH /{id}/` - Обновление (только owner)
- `POST /{id}/toggle_active/` - Активация/деактивация (owner)
- `POST /{id}/reset_password/` - Сброс пароля (owner)

### Склад (`/api/v1/warehouse/`)
- `GET /raw-materials/` - Список сырья
- `POST /raw-materials/` - Создание сырья
- `GET /raw-materials/{id}/` - Детали сырья
- `PATCH /raw-materials/{id}/` - Обновление сырья
- `GET /finished-products/` - Список готовой продукции
- `POST /finished-products/` - Создание продукции
- `GET /finished-products/{id}/` - Детали продукции
- `PATCH /finished-products/{id}/` - Обновление продукции

### Аудит (`/api/v1/audit/`)
- `GET /logs/` - Список audit logs (только owner)

## Запуск проекта

### Требования
- Python 3.11+
- PostgreSQL 14+
- Node.js (опционально, для инструментов)

### Установка

1. **Клонирование репозитория**
```bash
git clone <repository-url>
cd business-management-system
```

2. **Создание виртуального окружения**
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
```

3. **Установка зависимостей**
```bash
pip install -r requirements.txt
```

4. **Настройка переменных окружения**
Создайте файл `.env` в корне проекта:
```env
SECRET_KEY=your-secret-key-here
DB_NAME=skladpro
DB_USER=skladpro_user
DB_PASSWORD=your-password
DB_HOST=localhost
DB_PORT=5432
DEBUG=True
DJANGO_ENV=development
MEDIA_URL=/media/
MEDIA_ROOT=media/
```

5. **Создание базы данных**
```bash
psql -U postgres
CREATE DATABASE skladpro;
CREATE USER skladpro_user WITH PASSWORD 'your-password';
GRANT ALL PRIVILEGES ON DATABASE skladpro TO skladpro_user;
\q
```

6. **Миграции базы данных**
```bash
python manage.py makemigrations
python manage.py migrate
```

7. **Создание суперпользователя (опционально)**
```bash
python manage.py createsuperuser
```

8. **Запуск сервера**
```bash
python manage.py runserver
```

9. **Доступ к приложению**
- Frontend: http://localhost:8000/
- Admin panel: http://localhost:8000/admin/
- API: http://localhost:8000/api/v1/

## Где находится код для модификаций

### Backend (Python/Django)

**Модели данных:**
- `apps/core/models.py` - Базовые модели (TimestampedModel, SoftDeleteModel, Currency)
- `apps/accounts/models.py` - Модель User с ролями
- `apps/warehouse/models.py` - Модели склада (RawMaterial, FinishedProduct, StockMovement, Recipe)
- `apps/audit/models.py` - Модель AuditLog

**API Views:**
- `apps/accounts/views.py` - Аутентификация и управление пользователями
- `apps/warehouse/views.py` - API склада
- `apps/audit/views.py` - API audit logs

**Сериализаторы:**
- `apps/accounts/serializers.py` - Сериализаторы пользователей
- `apps/warehouse/serializers.py` - Сериализаторы склада

**Permissions:**
- `apps/core/permissions.py` - Кастомные permissions для RBAC (IsOwner, IsAdmin, IsWorker, FinancialDataPermission)

**Настройки:**
- `skladpro/settings/base.py` - Общие настройки Django
- `skladpro/settings/development.py` - Настройки для разработки
- `skladpro/settings/production.py` - Настройки для продакшена

### Frontend (JavaScript)

**API клиент:**
- `static/js/api.js` - APIClient для взаимодействия с backend

**Навигация:**
- `static/js/router.js` - Hash-based роутер
- `static/js/app.js` - Инициализация приложения

**Компоненты:**
- `static/js/components/dashboard.js` - Дашборд
- `static/js/components/warehouse.js` - Склад сырья
- `static/js/components/finished_products.js` - Готовая продукция

**Интернационализация:**
- `static/js/i18n.js` - Менеджер переводов
- `locale/uz_cyrl.json` - Узбекский (кириллица)
- `locale/ru.json` - Русский

### HTML Шаблоны

- `templates/base.html` - Базовый шаблон
- `templates/index.html` - Главный шаблон с навигацией
- `templates/accounts/` - Шаблоны авторизации

## Важные бизнес-правила

1. **Финансовые данные** (цены, себестоимость) доступны только владельцу (owner)
2. **Удаление пользователей** запрещено - используйте `toggle_active` для деактивации
3. **Владелец** не может быть деактивирован
4. **Администратор** может создавать только работников (при наличии разрешения)
5. **Audit logs** создаются автоматически для всех критических действий
6. **Мягкое удаление** (SoftDelete) используется для моделей склада - данные не удаляются физически

## Безопасность

- JWT токены с blacklist для refresh токенов
- Access токен живет 1 день, refresh токен - 7 дней
- Все API endpoints требуют аутентификации (кроме setup и login)
- RBAC для контроля доступа на основе ролей
- Audit logging для отслеживания всех действий
- Финансовые данные защищены permissions

## Поддерживаемые языки

- Узбекский (кириллица) - `uz_cyrl` (по умолчанию)
- Русский - `ru`

## Разработка

### Добавление новых полей в модели

1. Добавьте поле в `models.py`
2. Создайте миграцию: `python manage.py makemigrations`
3. Примените миграцию: `python manage.py migrate`
4. Обновите сериализатор в `serializers.py`
5. Добавьте комментарии и docstrings

### Добавление нового API endpoint

1. Создайте view в `views.py` с соответствующими permissions
2. Добавьте URL в `urls.py`
3. Создайте сериализатор если нужно
4. Добавьте docstring с описанием endpoint
5. Добавьте audit logging если это критическое действие

### Добавление нового языка

1. Создайте файл `locale/{lang_code}.json`
2. Добавьте переводы по структуре существующих файлов
3. Обновите `LANGUAGE_CODE` в settings если нужно

## Troubleshooting

**Проблема:** Ошибка подключения к базе данных
**Решение:** Проверьте настройки в `.env` и убедитесь что PostgreSQL запущен

**Проблема:** 401 Unauthorized при API запросах
**Решение:** Проверьте что JWT токен валиден и не истек

**Проблема:** Переводы не применяются
**Решение:** Проверьте что файлы переводов существуют и язык выбран правильно

## Онбординг сотрудников: Access Key (коды-приглашения)

Публичной регистрации нет. Аккаунты создаются внутри системы, сотрудник
активирует свой аккаунт кодом Access Key.

**Поток:** Супер-админ → компания (+ владелец) → сотрудник → система генерирует
Access Key → сотрудник вводит код при первом входе → аккаунт активируется
(сотрудник задаёт пароль) → вход. Код одноразовый.

**Модель** `apps/accounts/models.AccessKey`: `company`, `user`, `key`
(`SKP-XXXX-XXXX-XXXX`, уникальный), `status` (active/used/revoked),
`expires_at`, `used_at`, `created_by`. Свойства `is_expired`, `is_redeemable`,
`effective_status` (active/used/revoked/expired). Изоляция по `company`.

**Сервис** `apps/accounts/access_keys.py`:
- `issue_access_key(user, created_by, expires_in_days=None)` — выпуск; прежние
  активные ключи сотрудника отзываются (перевыпуск = один активный ключ).
- `verify_access_key(code)` — пригоден ли код (для первого экрана входа).
- `redeem_access_key(code, new_password)` — активация: пароль, `is_active=True`,
  ключ → `used`; возвращает `(user, None)` или `(None, reason)`. Одноразовость и
  проверка активности компании.
- `revoke_access_key(key)`.

**API** (`apps/accounts`):
- `POST /api/v1/accounts/users/{id}/access_key/` — выпуск/перевыпуск
  (owner/admin, только для сотрудников своей компании). `GET` — текущий активный.
- `POST /api/v1/accounts/access-key/verify/` — публичный, `{access_key}` → `{valid, employee?}`.
- `POST /api/v1/accounts/access-key/redeem/` — публичный, `{access_key, new_password}`
  → активация + JWT.
- Создание сотрудника (`POST /accounts/users/`) теперь допускает **отсутствие
  пароля** — тогда создаётся «приглашённый» аккаунт с непригодным паролем,
  активируемый через Access Key.
- Аудит: действия `ACCESS_KEY_ISSUED / ACCESS_KEY_REDEEMED / ACCESS_KEY_REVOKED`.

**Фронтенд:** экран «У меня есть код доступа» на `/accounts/login/`
(два шага: проверка кода → задать пароль → вход). i18n-ключи `auth.*`.

## Django Admin как панель управления ERP

Админка оформлена как панель управления (цветные бейджи, оптимизированные запросы):
- **Companies** — хаб компании: статус-бейдж, панель статистики (сотрудники по
  ролям, активные Access Key, навыки, клиенты, заказы), лента недавней активности
  (audit log), инлайн сотрудников; создание компании + владельца за один шаг;
  массовая блокировка/разблокировка.
- **Users** — бейджи роли и кадрового статуса, профиль (должность/отдел/даты/навыки),
  `filter_horizontal` навыков, инлайн Access Key, действия «сгенерировать Access Key»,
  блокировка/разблокировка.
- **Access keys** — код (копировать), сотрудник, статус-бейдж, фильтры,
  действия «отозвать»/«перевыпустить».
- **Skills** — каталог навыков компании со счётчиком сотрудников.
- **Warehouse/Orders** — бейджи остатков (мало/в норме) и статусов заказа/оплаты.
- Общий помощник бейджей: `apps/core/admin_utils.py`.

## Навыки сотрудников (Skills)

`apps/accounts/models.Skill` — каталог навыков компании (изоляция по `company`,
уникальность имени в пределах компании). M2M `User.skills`.
API: `/api/v1/accounts/skills/` (CRUD; чтение — любой сотрудник компании,
запись — owner/admin). Фильтр сотрудников по навыку: `/accounts/users/?skill=<id>`.

## Контакты

Для вопросов по проекту обращайтесь к разработчику.
