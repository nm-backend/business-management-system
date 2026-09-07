# SkladPro.Nod — карта проекта и результаты сплошного чтения кода

Дата: 7 сентября 2026. Ветка: `arena/01a07b5c-business-management-system` (от `057eba5`).
Метод: последовательное чтение всех слоёв — конфигурация → модели → сервисы → views/serializers →
права → фронтенд → инфраструктура → тесты и документация. Код не менялся: это аналитический документ.

---

## 1. Паспорт

| Параметр | Значение |
|---|---|
| Продукт | Multi-tenant SaaS ERP для камнеобрабатывающего производства (склад, заказы, производство, клиенты, финансы, чат, отчёты) |
| Стек | Django 5.1 + DRF + SimpleJWT, Channels (ASGI/daphne), Celery + django-celery-beat, PostgreSQL, Redis (обяз. в prod), vanilla-JS SPA на Django-шаблонах |
| Файлов в репозитории | 551 (425 `.py`, 29 `.js`, 12 `.html`, 12 `.md`, 8 `.json`, 5 `.css`) |
| Python-код | ~24 100 строк без тестов и миграций; 18 862 строки тестов (≈126 файлов `tests*.py`); 138 файлов миграций |
| Frontend | 9 «ядровых» JS-файлов (~1 760 строк) + 13 компонентов (~5 200 строк) + 5 CSS-слоёв (2 030 строк) |
| Локализация | `locale/{uz_cyrl,ru,ky}.json` по 804 строки, 35 корневых секций ключей; fallback — `uz_cyrl` |
| Приложения | `apps/`: core, companies, accounts, warehouse, orders, production, clients, finance, messaging, reports, audit, backup, billing + отдельный пакет `core/` (pagination/permissions/utils) |
| Документация | README (1 592 строки, фактически ТЗ+PRD), 4 ADR, senior-review (сент. 2026), UI/UX-аудит |
| Деплой | Dockerfile (multi-stage, python:3.13-slim, non-root uid 10001, daphne), docker-compose dev/prod, `render.yaml` (web + keyvalue + worker + beat) |
| CI | GitHub Actions: backend-тесты на PostgreSQL 16 + Redis (`ci_settings`), `manage.py check --deploy` на production-настройках, отдельный job — vitest |

> В данной песочнице зависимости не установлены (`pip list` пуст), поэтому тесты локально не запускались.
> По README/senior-review актуальные цифры: 1093 Django-теста + 74 vitest.

---

## 2. Как устроена система

### 2.1 Слои

```
templates/*.html  →  static/js (SPA, hash-router)  →  /api/v1/*  (DRF)
                                                       │
                        SubscriptionGateMiddleware ────┤ (403 subscription_expired)
                        SecurityHeadersMiddleware  ────┤ (CSP + nonce)
                                                       ▼
             permissions (IsCompanyMember / IsOwner… ) → views → services → models
                                                       │            │
                                                       │            └─ audit.write_audit_log
                                                       └─ messaging.notify / notify_staff (+ Web Push)
Celery: companies.tasks (auto-freeze, expiry-notify), backup.tasks, billing.tasks (делегаты)
Channels: ws/chat/ ← TicketAuthMiddleware ← WsTicket (одноразовый, 60 c)
```

### 2.2 Мультиарендность (ADR-001)

* Ключ изоляции — `company` FK на каждой бизнес-модели.
* `apps/core/views.CompanyScopedViewSet.get_queryset()` безусловно фильтрует `company_id=request.user.company_id`.
* Запись «чужих FK» перекрыта явными проверками: `OrderViewSet._assert_related_own_company`,
  `RecipeItemViewSet.perform_create/update`, `LaborRateViewSet`, `WorkerPaymentViewSet`,
  `PaymentViewSet.perform_create` (клиент + заказ + принадлежность заказа клиенту), `production.views` (task/product/worker).
* Глобальные справочники (Currency, ExchangeRate) — через `GlobalReferenceWriteMixin`: читают все, пишет только superadmin.
* Супер-админ платформы (`company=None`) не имеет доступа к бизнес-данным — ни в API, ни в SPA (маршруты заглушены 403).

### 2.3 Роли и доступ

| Роль | Что видит/может |
|---|---|
| `superadmin` | Только платформа: компании, подписки, счета, платформенный бэкап, свои уведомления |
| `owner` | Всё по своей компании + финансы (цены, себестоимость, прибыль, оплаты, аналитика, экспорт) |
| `admin` | Операционка без денег (двойные сериализаторы физически не отдают финполя) |
| `manager` | Чтение операционки (заказы, клиенты, склад, движения) без прав записи и без денег |
| `worker` | Только свои задачи/работы, свой заработок, чтение склада и ставок труда |

Разделение денег — ADR-002 (dual serializer): `*OwnerSerializer` vs базовый/`*Limited`; `FinancialDataPermission`
закрывает `finance`-эндпоинты целиком.

### 2.4 Складская семантика (ADR-003)

* `quantity` — физический остаток; `required_for_orders` — **потребность** заказов (не резерв), допускает overbooking;
  `available_quantity = quantity − required_for_orders` (может быть < 0), `shortage_quantity = max(required − quantity, 0)`.
* CHECK-ограничения только `>= 0`; связь «required ≤ quantity» намеренно отсутствует (в модели это прокомментировано).
* `warehouse/services.record_incoming` — блокировка строки, пересчёт средневзвешенной цены (`avg_cost_price` у сырья,
  `cost_price` у продукции) + `StockMovement.INCOMING`.
* `record_outgoing` не даёт списать зарезервированное, кроме `ignore_required=True` (выдача заказа).
* Ручного CRUD у `StockMovement` нет — история только след бизнес-операций; `price_per_unit` скрыт от не-owner,
  работник историю не видит вовсе.

### 2.5 Заказы

Статусная машина: `new ↔ awaiting_material → sent_to_worker → accepted → in_progress → awaiting_confirmation →
ready → delivered`, ветки `worker_refused`, `cancelled`. Переходы — только через `transition/deliver/cancel`
(права `IsOwnerOrAdmin`), `status`/`payment_status` read-only в сериализаторах.

Ключевые инварианты:
* `deliver` под `select_for_update`: снятие потребности → списание склада → при нехватке возврат потребности и
  понятная ошибка `not_enough_stock`; повторная выдача блокируется.
* Снимок COGS: `delivered_at` и `cost_price` фиксируются один раз при первом переходе в DELIVERED.
* `apply_payment_amount` — блокировка строки, запрет переплаты и оплаты отменённого заказа.
* Правка выданного заказа запрещена; смена клиента запрещена при наличии оплат; смена товара/количества
  корректно снимает старую потребность и ставит новую (кроме DELIVERED/CANCELLED).
* Потребность по сырью снимается с учётом уже списанного подтверждёнными работами (`PRODUCTION_OUT` по заказу) —
  защита от «двойного снятия» чужой потребности.

### 2.6 Производство

* `Task`: pending → accepted → completed → confirmed / refused / cancelled; двигают только action-эндпоинты.
* `WorkRecord`: `quantity` — годное, `defect_quantity` — брак. Сырьё списывается на `quantity + defect`,
  на склад приходуется только годное, оплата труда — только за годное.
* `confirm_work` (единственная операция, меняющая склад по производству) в одной транзакции:
  блокировка работы → проверка «зомби-заказа» → блокировка материалов в порядке pk → проверка нехватки →
  списание сырья и снятие потребности → приход товара с пересчётом средневзвешенной себестоимости
  (материалы по `avg_cost_price` + labor) → начисление → уведомление + audit.
* `MissingLaborRateError` (ставка не задана) вместо молчаливого нуля; `AlreadyProcessedError` (409) на гонках.
* `Task.confirm` переводит заказ в READY только если товара хватает под весь заказ (иначе остаётся в awaiting_confirmation).

### 2.7 Финансы и отчёты

* `Expense` (18 категорий), `LaborRate` (уникальность product+operation), `WorkerPayment` (потолок для типа «зарплата»).
* Удаление финансовых записей запрещено (`MethodNotAllowed`), правка пишется в audit; `Payment` вообще immutable.
* `reports/services.py` — чистый расчётный слой без HTTP: `revenue = Σ Payment`, `COGS = Σ quantity × cost_price`
  (по delivered в периоде), `net = revenue − COGS − (expenses − salaries) − worker_payments`,
  `cash = revenue − non-salary expenses − worker_payments`, дельты периода-к-периоду, таймлайн на 6 месяцев, квартальный отчёт.
* Экспорт xlsx/csv/pdf с защитой от formula injection (`_sanitize_xlsx_cell`, `_csv_safe_cell`) и кроссплатформенным
  поиском кириллического шрифта (`PDF_FONT_PATH` → DejaVu → Liberation → Arial).
* Агрегаты по работникам считаются по единицам измерения (`_finalize_worker_totals`): суммарное количество отдаётся,
  только если все работы в одной единице.

### 2.8 Подписки (два контура)

* **Источник истины** — `companies.Company`: `subscription_status` + `subscription_end` + `grace_period_days`,
  вычисляемый `effective_subscription_status` (active → grace → expired «на лету»).
* Все мутации — через `apps/companies/subscriptions.py` под `SELECT … FOR UPDATE`, с записью `SubscriptionChange`,
  audit-лога и уведомлений после коммита; Celery-задачи `auto_freeze_expired_subscriptions` и `notify_subscription_expiry`.
* `apps/billing` — второй контур: `Subscription` (OneToOne, планы free/pro), `SubscriptionEvent`, `Invoice`,
  payment-адаптеры (`manual` работает, `payme`/`click` — заглушки с фолбэком на manual), собственный API для owner
  и супер-админа. Зеркалирование двунаправленное (`_sync_billing_subscription` ↔ `_sync_company_fields`).
* Гейт: `apps/billing/gate.SubscriptionGateMiddleware` (403 `subscription_expired` для `/api/v1/*` кроме whitelist:
  логин/логаут/refresh/me/access-key/push/my-subscription/billing/core/схема) + `SubscriptionAccessPermission` в DRF.

### 2.9 Безопасность

* JWT: access 45 мин, refresh 7 дней, ротация + blacklist; **fingerprint-привязка** refresh (`fpr`-claim):
  несовпадение → blacklist всех токенов + `TOKEN_THEFT_DETECTED` + 401 `token_theft: true`.
* Регистрации нет: сотрудники активируются одноразовым `AccessKey` (`SKP-XXXX-XXXX-XXXX`, алфавит без 0/O/1/I).
  Выдача запрещена активированному аккаунту, заблокированному (`blocked_by_owner`) и аккаунту с 2FA; выпуск сериализован
  блокировкой строки пользователя (воспроизведённая гонка «3 активных ключа»).
* 2FA: TOTP (django-otp) + 10 резервных кодов по 80 бит; отключение требует пароль **и** код; модель угроз описана в docstring.
* WebSocket: одноразовый `WsTicket` (60 c, `select_for_update` при погашении, чистка и лимит 5 активных),
  проверка `is_active`/`blocked_by_owner`/активности подписки.
* Заголовки: CSP с per-request nonce (исключения `/admin/`, swagger, redoc), HSTS, X-Frame-Options DENY, referrer-policy.
* Троттлинг: user 300/min; scoped login 10/min, access_key_verify 10/min, access_key_redeem 5/min, two_factor 10/min —
  с ручным разбором XFF только от доверенных приватных прокси (Django 5.1 убрал `USE_X_FORWARDED_FOR`).
* Fail-closed production: отказ старта при коротком/дефолтном `SECRET_KEY` и при `ALLOWED_HOSTS='*'`;
  health-эндпоинт исключён из SSL-редиректа (грабли PaaS учтены).
* Первый супер-админ создаётся через `SetupGate` (pk=1, `select_for_update`) — гонка «двух первых владельцев» закрыта.

### 2.10 Фронтенд

* `api.js` — JWT + fingerprint в localStorage, авто-refresh с защитой от петли ретраев, AbortController-таймаут 30 c,
  обработка `subscription_expired` (экран «Подписка истекла» / однократная перезагрузка).
* `router.js` — hash-роутинг, подсветка меню, интеграция модалок с history (кнопка «назад» закрывает окно).
* `i18n.js` — загрузка `/api/v1/core/locale/<lang>/`, fallback на `uz_cyrl`, `data-i18n` и `data-i18n-attr` (aria/placeholder).
* `ui.js` — модалки, money/qty/date, donut-график, debounce, клиентское сжатие фото, `escape()` для всего пользовательского ввода.
* 13 компонентов страниц; Chart.js хранится локально (вендор), а не с CDN — цех со слабым интернетом.
* PWA: `manifest.json`, service worker отдаётся с корня (`/sw.js`) ради scope, Web Push (VAPID).

### 2.11 Инфраструктура

* Dockerfile multi-stage, `fonts-dejavu-core` для PDF, entrypoint: ждать БД → migrate → collectstatic →
  `ensure_superuser` → daphne; `SKIP_INIT=1` для worker/beat.
* `render.yaml`: web + keyvalue(Redis) + worker + beat, секреты из Environment Group, S3/R2 для медиа.
* Настройки: `base` → `development`/`production`, отдельные `test_settings` (SQLite in-memory) и `ci_settings` (PostgreSQL),
  `test_patch.py` — monkey-patch совместимости Django 5.1 с Python 3.14.

---

## 3. Что сделано сильно

1. **Комментарии-«почему»**: почти каждое нетривиальное решение подписано воспроизведённым инцидентом. Это резко
   снижает риск регрессии при рефакторинге.
2. **Конкурентность**: блокировки строк, фиксированный порядок захвата (материалы по pk), атомарные условные UPDATE
   (`last_reminder_at`), идемпотентность (повторный `confirm_invoice_paid`, повторная выдача), 409 вместо тихой перезаписи.
3. **Деньги**: Decimal + валидаторы + DB-констрейнты + снимки (`cost_price`, `delivered_at`) + owner-only сериализаторы.
4. **Изоляция**: три независимых слоя + отдельные наборы тестов (IDOR, cross-tenant, financial isolation).
5. **Тестовая дисциплина**: ~19k строк тестов, гонки прогоняются на настоящем PostgreSQL в CI + `check --deploy`.
6. **Единый путь бизнес-операций**: склад меняется только сервисами; статусы — только action'ами; удаления заменены архивом.

---

## 4. Находки этого прохода

### 4.1 Новое (не описано в существующих документах)

**F1. «Отправка файлов в чате» не работает — фича существует только на фронтенде.** (высокий)
`static/js/components/messages.js:492-510` шлёт `FormData` с полем `attachment` на `/api/v1/messaging/messages/`,
а `messageHtml()` (`:463`) рисует `m.attachment` / `m.attachment_name`. В бэкенде таких полей нет:
`apps/messaging/models.py` (`ChatMessage`: только `company/conversation/sender/content`),
`ChatMessageCreateSerializer.Meta.fields = ['conversation', 'content']`, `ChatMessageSerializer` не отдаёт вложений.
Итог: файл молча теряется, а сообщение **только с файлом** (без текста) падает с 400 → тост «ошибка».
Требуется модель/поле вложения + валидация типа и размера (`validate_file_size` уже есть) + отдача URL в сериализаторе.
Тестов на это нет (коммит `057eba5` заявляет фичу как готовую).

**F2. Панель «мониторинг долгов» на странице клиентов считает неверно.** (средний)
`static/js/components/clients.js:65-76`: `clients.reduce((sum, c) => sum + (c.debt || 0), 0)` — DRF отдаёт Decimal
строкой (`COERCE_DECIMAL_TO_STRING` не переопределён), поэтому происходит конкатенация строк, и
`window.ui.money()` (`Number(...)`) выводит `NaN сум`. Плюс запрос `/clients/clients/?is_archived=false` берёт
только первую страницу (`PAGE_SIZE=20`), т.е. и счётчик, и сумма занижены на больших компаниях.
Правильнее — серверный агрегат (`Sum('debt')` по неархивным клиентам) в отдельном эндпоинте или в
`reports` (там уже есть `client_debts`).

**F3. Два разных правила «потолка зарплаты».** (средний)
`apps/finance/serializers._SalaryCapMixin` считает уже выплаченное как **сумму всех** `WorkerPayment` работника,
а `apps/finance/views.WorkerPaymentViewSet.perform_create/perform_update` — только выплаты с
`payment_type=SALARY`. При наличии авансов две проверки дают разные лимиты и разные тексты ошибок
(сериализатор может отклонить то, что разрешает view, и наоборот). Нужно одно правило в одном месте
(ожидаемо — «зарплата ≤ начислено − выданные зарплаты», аванс учитывается отдельно как задолженность работника).

**F4. `my_earnings` считает «выплачено» без фильтра по компании и по всем типам выплат.** (низкий)
`apps/production/views.WorkRecordViewSet.my_earnings`: `WorkerPayment.objects.filter(worker=request.user)`
без `company_id`; при этом «остаток» включает авансы и премии, тогда как в `finance/settlements` формула та же,
а в проверке потолка (view) — другая. Стоит свести к общему сервису расчёта баланса работника.

**F5. Дрейф ADR-004 и кода.** (низкий, но вводит в заблуждение)
ADR-004 описывает тикеты в **Redis** с TTL 30 c и эндпоинт `/api/v1/accounts/ws-ticket/`, а также
`apps/accounts/ticket_auth.py`. Реально: модель `messaging.WsTicket` в БД, TTL 60 c (`WS_TICKET_TTL_SECONDS`),
эндпоинт `/api/v1/messaging/ws-ticket/`, middleware `apps/messaging/ws_auth.py`. ADR-003 тоже содержит
псевдокод `confirm_work`, отличающийся от реализации (нет `select_for_update` на work, другой расчёт).
ADR стоит привести к коду — иначе новый разработчик будет искать несуществующие модули.

**F6. Лента «Касса операциялари» на дашборде показывает только оттоки.** (низкий)
`static/js/components/dashboard.js:159-175` строит ленту из `/finance/expenses/` и `/finance/worker-payments/`
(обе с минусом). Поступлений (`/clients/payments/`) в ленте нет, хотя карточка «Касса» выше считается как
`revenue − расходы − выплаты`. Пользователь видит «кассу», в которой не бывает приходов.

**F7. Мелочи.**
* `templates/components/header.html` — пустой файл (0 строк), нигде не используется.
* `apps/billing/tasks.py` — задачи сняты с расписания миграцией `0004`, оставлены как делегаты; живой мёртвый код,
  который стоит удалить вместе с консолидацией подписок.
* `apps/messaging.NotificationViewSet.mark_read` делает полный `save()` вместо `update_fields`.
* В `_parse_period` (`apps/reports/views.py`) дважды импортируется `timezone` внутри функции.

### 4.2 Подтверждение известных пунктов (senior-review, сент. 2026)

* **P0 — два движка подписок** (`companies` vs `billing`): подтверждено полностью. Две модели, две истории
  (`SubscriptionChange` vs `SubscriptionEvent`), два каталога тарифов (`SubscriptionPlan.duration_days` против
  `settings.SUBSCRIPTION_PLANS` + жёсткого `SUBSCRIPTION_DAYS`), два набора API/UI, двунаправленное зеркало.
  GRACE в billing не представлен. Это по-прежнему главный архитектурный долг.
* **P1 — смешение единиц измерения**: склад и агрегаты по работникам исправлены (`unit_totals`), но
  `reports/views.AdminWorkExportView` (`Sum('quantity')` без группировки по `unit`) и `top_products`
  в `get_owner_analytics_data` (ранжирование по сумме количеств разных товаров/единиц) — остались.
* **P1 — уведомления не локализованы**: подтверждено: тексты жёстко зашиты (узбекские в бизнес-событиях,
  русские в подписках), язык получателя не учитывается.
* **P2 — уведомления внутри транзакции**: `OrderViewSet.deliver` вызывает `notify_staff`/`auto_archive`
  под `select_for_update` (в подписках принято «после коммита»).
* **P2 — фронтенд без сборки**: 22 скрипта подключаются на каждой странице из `base.html`, без `defer` и бандла.
* **P2 — Python 3.14 требует monkey-patch** шаблонов; целевой рантайм в Docker/CI — 3.13.

---

## 5. Рекомендованный порядок работ

1. **Починить или убрать «файлы в чате»** (F1) — сейчас пользователю обещана нерабочая функция.
2. **Серверный агрегат долгов** вместо клиентского суммирования (F2) — экран показывает `NaN`.
3. **Единая формула расчётов с работниками** (F3, F4) — вынести в `apps/finance/services.py`.
4. **Консолидация подписок (P0)**: companies-контур как агрегат, billing — тонкий адаптер счетов/провайдеров;
   удалить второй state machine и legacy-задачи, оставив cross-model тесты как страховку на время миграции.
5. **Локализация уведомлений** (шаблоны по i18n-ключам + язык получателя).
6. Довести единицы измерения в экспортe работ и `top_products`; актуализировать ADR-003/004; вынести уведомления
   за границу транзакций; лёгкий бандлер (esbuild) для SPA.

---

## 6. Карта файлов для быстрого входа

| Тема | Файлы |
|---|---|
| Конфигурация | `skladpro/settings/{base,development,production}.py`, `skladpro/{urls,asgi,celery,ci_settings,test_settings}.py` |
| Изоляция/права | `apps/core/{views,permissions,middleware,throttling}.py`, `core/permissions.py`, `docs/adr/001` |
| Склад | `apps/warehouse/{models,services,views,serializers}.py` |
| Заказы | `apps/orders/{models,serializers,views}.py` |
| Производство | `apps/production/{models,services,views,serializers}.py` |
| Финансы/отчёты | `apps/finance/*`, `apps/reports/{services,views}.py` |
| Подписки | `apps/companies/{models,subscriptions,tasks,views}.py`, `apps/billing/{models,services,gate,payments,views}.py` |
| Безопасность | `apps/accounts/{authentication,fingerprint_jwt,token_utils,access_keys,two_factor}.py`, `apps/messaging/ws_auth.py` |
| Чат/уведомления | `apps/messaging/{models,services,views,consumers,routing}.py` |
| Фронтенд | `static/js/{api,router,i18n,ui,app}.js`, `static/js/components/*`, `templates/base.html` |
| Инфраструктура | `Dockerfile`, `docker/entrypoint.sh`, `docker-compose*.yml`, `render.yaml`, `.github/workflows/test.yml` |
