# Senior-ревью SkladPro.Nod — сентябрь 2026

Дата: 6 сентября 2026
Метод: системный разбор «по порядку» — конфигурация и инфраструктура, бэкенд (models → services → views/serializers → permissions), безопасность, фронтенд (SPA), тесты и CI. Все выводы проверены по коду; ключевые тезисы прогнаны реальным запуском тестов.

---

## 0. Резюме

Проект — ERP для камнеобрабатывающего бизнеса (multi-tenant SaaS) на Django 5.1 + DRF + JWT, vanilla-JS SPA на Django-шаблонах, Channels/WebSocket чат, Celery + Beat, PostgreSQL (Redis опционально в dev, обязателен в prod). Платформенный супер-админ управляет компаниями и их подписками; внутри компании роли owner / admin / manager / worker с жёстким разделением финансов (видны только owner).

**Общее впечатление: зрелая, «выстраданная» кодовая база.** Видно много итераций исправлений реальных багов, каждое решение задокументировано прямо в коде (комментарии «почему», ссылки на воспроизведённые инциденты). Архитектурные решения зафиксированы в ADR. Изоляция арендаторов, денежная арифметика и гонки — на необычно высоком уровне для такого класса проектов. Тесты: **1093 Django-теста (OK, 19 skip)** и **74 фронтенд-теста (OK)**; в CI — PostgreSQL + Redis + `manage.py check --deploy`.

Основные риски не в «сломанном», а в **накопленном дублировании и рассинхронизации концепций**:

1. **Два параллельных движка подписки** (`apps.companies` vs `apps.billing`) с двунаправленным зеркалированием, двумя историями и двумя наборами API/UI — главный кандидат на консолидацию.
2. **Агрегаты, суммирующие количество в разных единицах** (например, «общий остаток» склада: кг + м + шт) — метрика без физического смысла.
3. **Серверные уведомления/push не локализованы** — язык текста не зависит от языка пользователя.
4. Менее критичные: разнобой контуров тестирования (SQLite локально / PG в CI), отсутствие бандлинга фронтенда, мелкие долги.

Детали и доказательства — ниже.

---

## 1. Паспорт и здоровье проекта

| Метрика | Значение |
|---|---|
| Коммитов в `main` | 160 (5 человек + 1 бот), период июль–сентябрь 2026 |
| Приложений (`apps/*`) | 13: core, companies, accounts, warehouse, orders, production, clients, finance, messaging, reports, audit, backup, billing |
| Python (без миграций/тестов ~) | ~36 500 строк (`wc -l`, без `migrations`, без `__pycache__`) |
| Модулей тестов | 126 файлов `tests*.py`, 1093 теста |
| JS (без vendor) | 22 файла, ~7 375 строк + vitest 74 теста (router/ui/i18n) |
| Фронт CSS | 5 слоёв: base 1167 → ux 230 → chat → enhance 111 → mobile 156 |
| Django-тесты (локально, SQLite) | 1093 OK, 19 skip, ~191 с |
| CI (`.github/workflows/test.yml`) | Backend на **PostgreSQL 16 + Redis** (`ci_settings`), затем `check --deploy` на `production`-настройках; отдельный job — vitest |
| Docker | Python 3.13-slim, multi-stage, non-root (uid 10001), daphne, healthchecks |
| Деплой-таргеты | Render blueprint (`render.yaml`), docker-compose dev/prod (prod — fail-closed: обязательные секреты, без `*` в ALLOWED_HOSTS) |

Запуски, сделанные при ревью:

```bash
# полный набор Django (SQLite, локально)
DJANGO_SETTINGS_MODULE=skladpro.test_settings python manage.py test
#   → Ran 1093 tests in 190.890s — OK (skipped=19)

npx vitest run
#   → 3 files, 74 tests passed
```

---

## 2. Архитектура: как всё устроено

### 2.1 Слои и изоляция арендаторов

- **Ключ изоляции** — `company` (ForeignKey на `companies.Company`) на каждой бизнес-модели. Базовый `CompanyScopedViewSet` (`apps/core/views.py`) безусловно фильтрует `get_queryset()` по `request.user.company_id`.
- **Защита от «чужих FK»** на записи: `OrderViewSet._assert_related_own_company`, аналогичные проверки в warehouse (recipe/recipe_item/product), accounts (skill), finance и т.д. — нельзя привязать объект чужой компании (IDOR).
- **Два страховочных слоя подписки**: `SubscriptionGateMiddleware` (ранний 403 для `/api/v1/*`) + `IsCompanyMember`/`SubscriptionAccessPermission` в DRF (защита даже там, где view переопределила `permission_classes`).
- Изоляция подтверждена отдельными наборами тестов: `tests_cross_tenant_*`, `tests_idor.py`, `tests_financial_isolation_v2.py`, `tests_money_isolation*`, `tests_superadmin_isolation_k.py`, `tests_cross_tenant_reads_k.py`, `tests_ws_isolation_k.py`.

### 2.2 Деньги и бизнес-инварианты

- **Decimal** на всех денежных полях + `MinValueValidator` + DB `CheckConstraint` (`quantity >= 0`, `required_for_orders >= 0`).
- **Двойные сериализаторы по роли** (ADR-002): owner-сериализатор отдаёт финансы, остальные роли их физически не получают от API — «фронтенд не может показать то, что бэкенд не отправил».
- **Demand vs физический остаток** (ADR-003): `required_for_orders` — потребность заказов, может превышать остаток (overbooking), нехватка показывается `shortage_quantity`, проверка — в момент выдачи/подтверждения.
- **Снимки вместо живых ссылок**: `Order.delivered_at` и `Order.cost_price` фиксируются один раз при переходе в DELIVERED (поздняя оплата/переоценка не переносят прибыль между периодами).
- **Средневзвешенная себестоимость** пересчитывается сервером в `record_incoming` (и для сырья, и для продукции — был баг, когда продукция молча теряла цену) и в `confirm_work` (себестоимость партии = сырьё по рецепту + оплата труда).
- **Журнал движений** `StockMovement` — история создаётся только бизнес-операциями (приход/расход/производство), ручного create/delete нет.

### 2.3 Конкурентность

Авторы системно боролись с гонками: `select_for_update` + `transaction.atomic` в `record_incoming/outgoing`, `Order.apply_payment_amount` (оплата под блокировкой строки, защита от переплаты), `deliver/cancel/unwind` (двойная выдача/двойной возврат), `confirm_work` (`AlreadyProcessedError`), `get_or_create_direct` (блокировка строк обоих пользователей), тикеты WS. Везде, где берётся несколько блокировок, — фиксированный порядок (например, материалы сортируются по pk), чтобы избегать deadlock'ов. Комментарии в коде описывают воспроизведённые гонки и почему именно так.

### 2.4 Безопасность

- **JWT**: access 45 мин / refresh 7 дней, rotate + blacklist. **Fingerprint-привязка refresh-токена** (SHA-256 от device-id в claim `fpr`): несовпадение → детект кражи → blacklist всех токенов + audit-запись `TOKEN_THEFT_DETECTED` (`apps/accounts/fingerprint_jwt.py`).
- **Доступ сотрудников**: публичной регистрации нет — owner/superadmin выдают одноразовые `AccessKey` (`SKP-XXXX-XXXX-XXXX`), активация задаёт пароль; 2FA (TOTP django-otp) + резервные коды; блокировки пользователя/компании инвалидируют refresh.
- **WebSocket**: access-токен не уходит в query-строку — одноразовые WS-тикеты TTL 60 c (ADR-004), `select_for_update` при погашении, очистка старых тикетов.
- **HTTP-заголовки**: CSP с nonce (скрипты; `/admin`, swagger — в исключениях), Permissions-Policy, X-Frame-Options, HSTS, referrer; `style-src 'unsafe-inline'` — осознанный компромисс из-за инлайн-атрибутов.
- **Троттлинг**: login/access_key/2FA по IP **с доверием XFF только от приватных прокси** (Django 5.1 убрал USE_X_FORWARDED_FOR — сделано вручную в `apps/core/throttling.py`).
- **Fail-closed production**: `production.py` отказывается стартовать с коротким/дефолтным SECRET_KEY и с `ALLOWED_HOSTS='*'`; prod-compose требует обязательные секреты `${VAR:?}`.
- **Гигиена репозитория**: `.env`, `*.sqlite3`, `.freebuff/*.db` — в `.gitignore` (проверено `git check-ignore`), в git только `.env.example`.

### 2.5 Фронтенд

- Hash-роутер (`router.js`) + компоненты с общими `list-states` (loading/skeleton/empty/error/retry), `ui.js` (модалки, форматирование, debounce, сжатие фото на клиенте), i18n-менеджер (3 локали: `uz_cyrl` — fallback, `ru`, `ky`), WebSocket-клиент чата на тикетах.
- **XSS-дисциплина**: весь пользовательский контент проходит `window.ui.escape(...)` (проверено по components — клиенты, чат, заказы, склад, производство и т.д.); есть unit-тесты на экранирование.
- Роуты и пункты меню фильтруются по роли на клиенте, но **все проверки продублированы на сервере** (это правильно).
- SaaS-гейт на фронте: экран «Подписка истекла», баннер льготного периода, обработка 403 `subscription_expired` → перезагрузка bootstrap'а.

### 2.6 Инфраструктура

- Docker multi-stage (компиляторы только в builder), non-root, healthcheck реальным HTTP-запросом, entrypoint ждёт БД → миграции → collectstatic. dev/prod compose разведены: prod — без монтирования кода, обязательные секреты, `SECURE_SSL_REDIRECT`.
- Celery: worker + beat (DatabaseScheduler); миграции компаний создают расписания авто-заморозки/уведомлений.
- Observability: логи в stdout, уровни SQL, Sentry (DSN-опционально), health-endpoint вне троттлинга и вне HTTPS-редиректа (учтены грабли PaaS).

---

## 3. Ключевые находки (по приоритету)

### P0 — Два параллельных движка подписки (`apps.billing` vs `apps.companies`)

**Факты из кода:**

- Две модели одного понятия: `Company.subscription_*` + `Company.plan` (FK на `SubscriptionPlan`) vs `billing.Subscription` (OneToOne, свой `plan` из каталога `'free'/'pro'`), `SubscriptionChange` vs `SubscriptionEvent`, `Invoice`/`SubscriptionEvent` — только в billing.
- `billing/gate.py` прямо признаёт: *«Единственный источник истины — Company.effective_subscription_status»*, и комментирует прошлый баг, когда fallback по `billing.Subscription.is_blocked` блокировал компании в льготном периоде (GRACE).
- Зеркалирование **двунаправленное**: `companies/subscriptions.py::_sync_billing_subscription` (Company → billing, и только если billing-строка уже есть) и `billing/services.py::_sync_company_fields` (billing → Company, включая запись `is_trial`). Обе пишут одни и те же поля Company — два автора состояния.
- **Два набора API и UI**: суперадмин-SPA (`companies.js`) ходит и в `/companies/{id}/subscription_extend|subscription_change_plan|subscription_set_end|plans/`, и в `/billing/subscriptions/{id}/extend|activate|freeze|unfreeze|confirm_payment`; владелец — в `/billing/subscription/*` (`subscription.js`, `settings.js`) и `/companies/my-subscription/request-renewal/` (`app.js`).
- **Две истории**, которые не сводятся: зеркала не пишут события контура-приёмника → продление через companies-контур не создаёт `SubscriptionEvent`, через billing-контур — не создаёт `SubscriptionChange`. Владелец и суперадмин видят разные «истории» одной компании.
- **Два каталога тарифов**: `SubscriptionPlan` (FK, `duration_days`) и `settings.SUBSCRIPTION_PLANS` + `billing.Subscription.plan`; срок продления в billing жёстко `settings.SUBSCRIPTION_DAYS`, а не `plan.duration_days`.
- GRACE не имеет аналога в billing (зеркалится в `active`, но `expires_at` в прошлом → `billing.is_blocked=True`): решения, принятые по billing-модели (например, `quick_renew_subscription` выбирает ACTIVATED/EXTENDED по `is_blocked`), «не знают» про льготный период.
- Legacy-код billing сохраняется: `billing/services.py` (~430 строк) содержит второй полный lifecycle (`freeze_subscription`, `renew_subscription`, ...), `billing/tasks.py` — задачи, чьё расписание было удалено миграцией `0004_remove_beat_schedule` (активны компании-задачи). Cross-model тесты (`tests_consistency_k`) держат статусы в согласии — но ценой поддержания зеркал.

**Почему это проблема:** сейчас «работает», но любой новый сценарий (реальная оплата Payme/Click, частичное продление, заморозка по требованию провайдера) придётся писать дважды или он разойдётся; зеркала — источник уже случившихся прод-инцидентов (см. комментарии). Это главный архитектурный долг.

**Рекомендация:**
1. Оставить единым агрегатом **companies-контур** (в нём grace, effective-статус, единый гейт и SubscriptionChange-история).
2. `apps.billing` свести к тонкому адаптеру: счета `Invoice` + `payments` (провайдеры) + read-only API для UI, читающее состояние из Company.
3. Удалить второй state machine: `billing.Subscription.status/expires_at/plan` lifecycle, `SubscriptionEvent`-дубль (или превратить в проекцию), legacy-задачи/сервисы после grep-анализа вызовов (`freeze_subscription`, `renew_subscription`, `send_expiry_reminders` — используются в основном тестами).
4. Единый каталог планов (один FK, одна длительность); один путь продления.
5. Пока рефакторинг идёт — оставить cross-model тесты как защиту от дрейфа.

### P1 — Агрегаты, суммирующие количество в разных единицах — ✅ исправлено 2026-09-06 (склад сырья)

Было: `apps/warehouse/views.py::summary` считал `total_quantity = SUM(quantity)` по всем позициям независимо от единицы — «5 кг + 3 м + 2 шт = 10», голое число без единицы в карточке «Жами қолдиқ».

Стало: остатки группируются по единице (`unit_totals`), а `total_quantity` отдаётся только когда всё сырьё в ОДНОЙ единице (иначе `null`). Фронтенд (`warehouse.js::loadSummary`) показывает единый итог с единицей измерения, а при смешанных единицах — разбивку по строкам. Тесты: `test_summary_does_not_mix_units`, `test_summary_single_unit_shows_total`, `test_summary_archived_excluded` (92 теста warehouse + 74 vitest — зелёные). Стоимость (`total_value` = Σ quantity×avg_cost_price) корректна и не менялась: цены заданы за единицу конкретного материала.

Ещё проверить (тот же класс бага, не входит в этот фикс): агрегаты по работнику в разных единицах — `reports/services.py` `top_worker`/`worker_performance` (`Sum('quantity')` по всем подтверждённым работам работника без группировки по `unit`) и карточка «Самый активный работник» на дашборде.

### P1 — Агрегаты работников в разных единицах — ✅ исправлено 2026-09-06

Было: `reports/services.py` считал `total_quantity = SUM(quantity)` по всем подтверждённым работам работника без учёта `unit` (и `top_worker` → карточка «Самый активный работник», и `worker_performance` в админ-аналитике): «3 м + 2 шт = 5» без единицы; ранжирование «самого активного» шло по этой бессмысленной сумме (500 шт < 300 м + 200 шт).

Стало: общий хелпер `_finalize_worker_totals` — группировка по (работник, единица), `total_quantity` только при единой единице (иначе `null`), `unit_totals` по убыванию. Ранжирование: если в выборке встречается больше одной единицы, сравнение по количеству некорректно для всех — сортировка по числу подтверждённых работ (`works`, единица-агностик); при единой единице — по количеству, как раньше. Фронтенд (`dashboard.js::workerOutput`) показывает «N шт» с единицей, а при смешанных единицах — разбивку. Тесты: 5 новых в `tests_deep_fix_k.py` (`WorkerAggregatesUnitTests`): одно- и разно-единичные итоги, оба правила ранжирования, `worker_performance` (60 тестов reports + 74 vitest — зелёные).

Ещё остался тот же класс бага: `views.py::AdminWorkExportView` (экспорт «Выработка работников» — `Sum('quantity')` без `unit`) и `top_products` (ранжирование/сумма по товарам в разных единицах).

### P1 — Серверные уведомления и push не локализованы

`locale/*.json` переводит только SPA. Серверные `Notification`/push пишутся вперемешку: по-узбекски (`'Янги буюртма'`, `'Иш тасдиқланди'`, `'Мижоз тўлов қилмади'`), по-русски (подписки: `'Подписка продлена до …'`, audit-тексты). У пользователя с `language=ru` или `ky` уведомления приходят не на его языке; в одном колокольчике могут встретиться оба языка. Это заметный UX-дефект для трёхязычного продукта.

**Рекомендация:** сервис уведомлений с шаблонами по i18n-ключам и языком получателя (хранить текст на языке адресата в момент создания), пуш — тем же путём.

### P2 — Разнобой контуров тестирования конкуренции

Локально (и в этом ревью) полный набор идёт на SQLite `:memory:` (`test_settings`), где `FOR UPDATE` — no-op, поэтому «гонко-защитные» тесты на SQLite ничего не доказывают. Это **закрыто CI**: `ci_settings` + PostgreSQL в workflow. Пробел только DX: гонки нельзя воспроизвести локально без поднятого PG. Рекомендация: короткая инструкция/скрипт `docker compose run` с `--settings=skladpro.ci_settings` для локального прогона гонок; можно сузить набор race-тестов, чтобы локальный полный прогон оставался быстрым.

### P2 — Фронтенд: нет сборки/минификации

22 скрипта (7.4k строк) подключаются на **каждую** страницу из `base.html` (без `defer`, без бандла): лишние килобайты и блокировка парсинга на слабых каналах (а «слабый 3G/4G в цеху» — прямое требование продукта, ради которого уже делали сжатие фото). `?v=ASSET_VERSION` решает кэш, но не объём.

Рекомендация (поэтапно, без революции): лёгкий бандлер (esbuild) → 1–2 бандла + minify; затем — постраничная подгрузка тяжёлых компонентов (finance/chart). Низкий приоритет, но ощутимо для целевой аудитории.

### P2 — Мелкие долги и наблюдения

- **Версии**: Django 5.1.x на Python 3.13 (Docker/CI) — ок; локальный Python 3.14 требует monkey-patch шаблонов (`skladpro/test_patch.py`). Стоит перейти на Django 5.2 LTS (долгосрочная поддержка) и зафиксировать Python 3.13.
- **Уведомления внутри транзакций**: в `Order.deliver` `notify_staff`/auto-archive выполняются под блокировкой строки заказа; в подписочном контуре принято отправлять уведомления после коммита. Единообразие стоило бы привести к «после коммита».
- Небольшие legacy-поля: `Skill.company` nullable (глобальный каталог навыков не используется, но поле допускает); комментарии с примерами дат «2024-05-25» (косметика).
- Аудит-лог админских действий покрыт частично через переопределения `save_model`/actions — проверить полноту, если нужен полный след изменений из `/admin`.
- В коде встречается смешение русского и узбекского в пользовательских строках ошибок (например, некоторые DRF-сообщения на русском при узбекском интерфейсе) — точечно привести к i18n-стратегии из P1.

---

## 4. Что сделано сильно (беречь при рефакторингах)

- **Документирование решений в коде и ADR**: 4 ADR (изоляция, dual-serializer, demand/COGS-snapshot, WS-тикеты) + комментарии-истории багов. Это резко снижает стоимость входа и риск регрессий.
- **Изоляция арендаторов**: единая модель `Company`-scoping + проверки FK на запись + три независимых набора тестов (IDOR, cross-tenant, финансовые).
- **Денежная точность**: Decimal + валидаторы + DB-ограничения + owner-only сериализаторы + снимки стоимости — связка, которой нет во многих ERP.
- **Практика race-фиксов**: блокировки строк, атомарные условные UPDATE (напр. `last_reminder_at`), фиксированный порядок блокировок, race-тесты — уровень выше среднего.
- **Безопасность как система**: fingerprint-JWT, одноразовые access-keys, 2FA, WS-тикеты, CSP-nonce, fail-closed prod-настройки, non-root в Docker, чистый git (секреты не закоммичены).
- **CI**: полный прогон на PostgreSQL+Redis + `check --deploy` + фронтенд-тесты — редкая дисциплина.
- **Frontend XSS-гигиена** и осознанный минимализм (vanilla SPA без тяжёлых фреймворков, вендорная Chart.js).

---

## 5. Предлагаемый порядок работ

1. **Консолидация подписок (P0)** — самый ценный рефакторинг; начать с инвентаризации вызовов billing-сервисов, затем перевести UI/API на companies-контур и удалить второй state machine.
2. **Исправить/уточнить агрегаты в единицах (P1)** — warehouse summary + проверка dashboard-агрегатов.
3. **Локализация уведомлений (P1)** — единый шаблонный слой, язык получателя.
4. Локальный PG-профиль для гонок + бандлинг фронтенда (P2) — по мере ресурсов.

---

## Приложение: карта изучения (файлы-ориентиры)

- Конфигурация: `skladpro/settings/base.py`, `production.py`, `development.py`, `urls.py`, `.github/workflows/test.yml`
- Изоляция/права: `apps/core/views.py`, `apps/core/permissions.py`, `core/permissions.py`, `docs/adr/001`
- Домены: `apps/{warehouse,orders,production,clients,finance,accounts,messaging,audit,billing,backup,companies,reports}/models.py` + `services.py` (склад, производство, подписки)
- Безопасность: `apps/accounts/{fingerprint_jwt,authentication,two_factor,access_keys}.py`, `apps/messaging/ws_auth.py`, `apps/core/middleware.py`
- Фронтенд: `static/js/{api,router,app,ui,i18n}.js`, `static/js/components/*`, `templates/base.html`
