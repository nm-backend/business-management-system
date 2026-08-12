# UI/UX Аудит — SkladPro.Nod

Дата: 2026-08-11
Контекст: ревью коммита `b54fe16` («Copilot make ui ux») + полное изучение фронтенда.
Статус: документ живой, обновляется по мере исправлений.

---

## 1. Обзор архитектуры фронтенда

- **Стек**: Django-шаблоны + vanilla-JS SPA. Роутер (`router.js`) рендерит компоненты в `#app-content`; роль (`currentUser`) определяет, что видит пользователь.
- **Общие модули**: `ui.js` (модалки, debounce, форматирование), `list-states.js` (gone/skeleton/empty/error), `icons.js` (SVG Lucide-иконки), `i18n.js` (data-i18n, 3 локали: ru, uz_cyrl, ky), `toast.js`, `dialogs.js` (confirmation).
- **CSS-слои** (в порядке подключения): `base.css` (дизайн-система, 1167 строк) → `ux.css` (тосты, ошибки, сканер) → `chat.css` → `enhance.css` (a11y-полировка) → `mobile.css` (touch-адаптация).
- **Дизайн-система**: токены в `:root` (teal-slate `#197387` + copper `#d67a4b` на limestone paper), тёмная тема `body.theme-dark`, шрифты Fraunces (display) / Inter (body) / JetBrains Mono (данные) с Google Fonts, radius 14px, мягкие тени.
- **Роли**: superadmin / owner / admin / manager / worker. Права: редактирование — owner+admin; деньги — только owner.

## 2. Что уже хорошо (сохранять)

- Полноценная дизайн-система с токенами и тёмной темой.
- `skip-link`, `:focus-visible` везде, `prefers-reduced-motion`, тач-цели ≥44px, safe-areas (iPhone), фиксы overscroll/рипл — в `enhance.css`/`mobile.css`.
- `window.listStates` (gone/skeleton/empty/error + retry) — последовательно в orders, warehouse, clients, finished_products, audit, notifications.
- SVG-иконки `icons.js` (Lucide) — есть инфраструктура.
- Чат: корректный ARIA-табы, `role="button"`+keydown у уведомлений.
- i18n-тесты (`apps/core/tests_i18n_keys_k.py`) ловят отсутствующие ключи.
- Комментарии фиксируют историю багов (сильная сторона кодовой базы).
- Скелетоны, микро-анимации, donut-чарт, metrics-grid, page-hero — единый визуальный язык.

## 3. Баги (исправлено 2026-08-11)

| # | Место | Проблема | Статус |
|---|-------|----------|--------|
| 1 | `finance.js:25` | `user` не объявлен → ReferenceError, страница Финансов не рендерилась полностью | ✅ h2 заменён на `data-i18n="nav.analytics"` |
| 2 | `finance.js:86-114` | Период-табы удалены из аналитики (обработчик был мёртвым, период вечно `month`) | ✅ табы восстановлены |
| 3 | `locale/*.json` | `finance.analytics_breakdown` отсутствовал во всех локалях | ✅ добавлен |
| 4 | `locale/*.json` | `production.open_tasks` отсутствовал во всех локалях (старый долг) | ✅ добавлен |
| 5 | `locale/uz_cyrl,ky.json` | `dashboard.overdue_orders` отсутствовал (был только в ru) | ✅ добавлен |

Проверка: `python manage.py test apps.core.tests_i18n_keys_k` — 4/4 OK.

## 4. Функциональные риски (P0 — чинить)

| # | Место | Проблема |
|---|-------|----------|
| 1 | `kanban.js:215` | `setTimeout(() => this.loadOrders(), 300)` после move без `listStates.gone()` — запрос в никуда после ухода со страницы | ✅ gone()-гард в `loadOrders` |
| 2 | `messages.js:93` | reconnect `setTimeout` не сохраняется в поле → не отменяем; `shouldRun` никогда не `false`; у `ChatSocket` нет `disconnect()`/teardown при logout — WS живёт весь жизненный цикл приложения | ✅ `reconnectTimer` отменяемый + `disconnect()` + вызов в `api.logout()` |
| 3 | `messages.js:183,267` | дебаунс поиска сотрудников не очищается; `searchEmployees`/`renderList` пишут в отсоединённый `#chat-list` без `gone()` | ✅ gone()-гарды |
| 4 | `kanban.js:51` | кнопка `#kanban-view-btn` рендерится без обработчика — мёртвый элемент управления | ✅ заменена на `<span class="tab-btn active">` (это индикатор текущей вкладки, не действие) |
| 5 | `router.js` + `base.html` | роут `#/orders/kanban` осиротевший: ни одной навигационной ссылки, попасть можно только вручную | ⏳ решение за продуктом (роут рабочий, ссылки нет) |
| 6 | `orders.js:353` | `const unitOptions = unitSelect.innerHTML` — неиспользуемая переменная | ✅ удалена |
| 7 | `warehouse.js:314-319` | keydown Enter/Space на `div.list-row` без `tabindex` — никогда не сработает | ✅ `role="button" tabindex="0"` добавлены |

## 5. Доступность (P1)

| # | Место | Проблема | Рекомендация |
|---|-------|----------|--------------|
| 1 | `kanban.js:144`, `clients.js:65`, `warehouse.js:329` | кликабельные `<div>` без `role="button"`/`tabindex` (в `orders.js:151` паттерн правильный — расхождение) | ✅ role/tabindex + keydown во всех трёх |
| 2 | `messages.js:325,338` | английские `aria-label="Back"/"Send"` в русско-узбекском UI | ✅ через новый `data-i18n-attr` (i18n.js:70) |
| 3 | `warehouse.js:47-48` | кнопка сканера `📷` без доступного имени (нет текста/aria-label) | ✅ `data-i18n-attr="aria-label"` + ключ `warehouse.scan_barcode` |
| 4 | `orders.js:58`, `warehouse.js:45`, `messages.js:168`, `clients.js:18` | инпуты поиска без `<label>`/`aria-label`, только placeholder | ✅ `data-i18n-attr="placeholder,aria-label"` |
| 5 | `messages.js:335` | лента сообщений без `aria-live="polite"` — новые сообщения не озвучиваются | ✅ добавлен |
| 6 | все табы (orders:46, warehouse:22, finance:28, dashboard:37) | нет `aria-controls`, нет навигации стрелками | ⏳ отложено (messages уже с aria-controls; roving tabindex — отдельная итерация) |
| 7 | декоративные эмодзи-иконки (🔍 📷 и т.п.) | без `aria-hidden="true"` | ✅ поисковые иконки; остальные — вместе с переходом на SVG |

## 6. Консистентность (P2)

### 6.1 Эмодзи вместо SVG-иконок
`icons.js` даёт `window.icon('name', size)`, но компоненты используют сырые эмодзи:
- канбан: иконки колонок `📋 📦 📨 ✅ 🛠️ ⏳ 🎯 ✓` (kanban.js:25-32), кнопки `🔄`, предупреждения `⚠️ 💰 ⏰`
- уведомления: `notificationStyle` (messages.js:525-534) — 15 эмодзи
- кнопки действий `✏️ 🗑️` (finance.js:186-187, messages), поиск `🔍`, сканер `📷`, alert-box `⚠️`
- пустые состояния: `📭` (list-states CSS)

### 6.2 Инлайн-стили (~200 вхождений)
Самые частые паттерны, которые должны стать CSS-классами:
- `style="cursor:pointer"` / `cursor:default`
- `style="display:flex;align-items:center;gap:12px"` и сетки `grid-template-columns:1fr 1fr;gap:10px`
- `style="box-shadow:none;border:1px solid #efeff4"` — **хардкод-цвет расходится**: в settings.js `var(--border-color)`, в finished_products.js:143,318 и orders.js:203, warehouse.js:357 — `#efeff4`
- `style="min-width:0"`, `text-align:right`, `font-weight:600;font-size:14px`

### 6.3 Ручной debounce вместо `window.ui.debounce` (ui.js:269)
clients.js:33, messages.js:178, orders.js:64, warehouse.js:102, finished_products.js:53 — 5 копий. ✅ все заменены на `window.ui.debounce`.

### 6.4 listStates-миграция не завершена
- kanban.js: ✅ error-состояние переведено на `listStates.error` с retry; загрузка/пустота — по-прежнему колонки (осознанно)
- messages.js (чат): ⏳ свои `.chat-empty`/`list-state` (L204, 211, 227, 273, 368, 373, 382), хотя уведомления того же файла уже на listStates

### 6.5 Дублирование между компонентами
- проверка `user.is_owner || user.is_admin` — 6+ файлов (кандидат на helper)
- keydown Enter/Space — дословно в orders.js:135 и warehouse.js:314
- сабмит-обработчики модалок (submitGuard + api + toast + reload) — 6 повторений
- разметка row детали (row/detailRow) — orders.js:176 ≈ warehouse.js:457
- toggle табов — цикл по кнопкам в каждом компоненте

### 6.6 Заголовок страницы
- `#page-title` через data-i18n (orders, finance, messages, clients…), но kanban.js:12-17 вынужден `removeAttribute('data-i18n')` из-за бага «перевод с прошлой страницы» — несовместимые подходы.

## 7. i18n и переводы (P2)

- Тесты: `apps/core/tests_i18n_keys_k.py` — 4 теста зелёные.
- **ky.json**: «ўтиш»→«өтүү» (open_orders), узбекский worker_overview → кыргызский ✅
- Английские aria-label интернационализированы через `data-i18n-attr` (новая возможность i18n.js) ✅
- `ky.json:126` `overdue_percentage` = «Мөөнөтү өткөн буйрутмалар» — согласовано с новым `overdue_orders`.

## 8. Утечки/гонки (P1)

| Место | Что | Статус |
|-------|-----|--------|
| messages.js:64 | ping WS 25c | ✅ очищается |
| messages.js:93 | reconnect | ✅ disconnect()/teardown при logout (api.js:216), отменяемый reconnect, лимит 15с |
| kanban.js:215 | loadOrders через 300мс | ✅ gone()-проверка в начале loadOrders (kanban.js:39) |
| kanban.js:136 | setTimeout dragging | ✅ безвреден (0мс, класс анимации) |
| orders/warehouse/clients/finished_products | дебаунс поиска | частично: таймер не чистится, но запросы защищены gone() |
| app.js:82 | setInterval badge 60c | глобальный, намеренно |
| warehouse.js:222 | scanLoop 400мс | ✅ флаг stopped + MutationObserver |
| finance.js:70-130 | период-табы | ✅ восстановлено |

## 9. План улучшений

### P0 — функциональность (ближайшая итерация)
1. ✅ `kanban.js`: gone()-проверка в loadOrders есть; переключатель «Список | Канбан» добавлен на страницу заказов (orders.js) и в канбан (kanban.js); роут `/orders/kanban` доступен из UI, заголовок локализован (`orders.view_list`/`orders.view_kanban` во всех 3 локалях)
2. ✅ `messages.js`: `disconnect()`/teardown ChatSocket при logout (api.js:216), отменяемый reconnect
3. ✅ `warehouse.js`: role="button" tabindex="0" + keydown Enter/Space (warehouse.js:330, 315-320)
4. ✅ `orders.js:353`: переменная используется (availabilityBox)
5. ✅ `core/utils.py`: `lru_cache` для локалей заменён на кэш с проверкой mtime — правки переводов видны без рестарта сервера

### P1 — доступность
1. role="button"+tabindex на кликабельных карточках (канбан, клиенты, склад)
2. aria-label через i18n (сканер, поиск, Back/Send)
3. aria-live в чате, aria-controls/стрелки в табах

### P2 — консистентность (долг)
1. Перевести уведомления/канбан/кнопки действий на `window.icon()` (SVG) — поэтапно, чтобы не раздуть дифф
2. Вынести инлайн-паттерны в CSS-классы: `.row-flex`, `.row-grid-2`, `.list-group-nested` (заменить #efeff4 на var(--border))
3. `window.ui.debounce` вместо ручных копий
4. listStates в канбан и чат
5. Починить переводы ky.json (§7)

### P3 — дизайн-полировка (после консистентности)
- Единый hero-паттерн на всех страницах (сейчас page-hero только: dashboard, finance, orders, warehouse, finished_products, settings-профиль; clients/audit/messages — без)
- Пересмотр пустых состояний: data-empty-message/data-empty-action (list-states.js поддерживает, нигде не используется)
- Проверить контраст `#8a6618` (badge-progress) на `--warning-soft` — подозрительно тёмный

---

## 11. Редизайн в стиле Apple (2026-08-11, в работе)

Решение пользователя: **светлый монохром по умолчанию** (тёмная тема — как опция, toggle уже есть), фирменные teal/copper убраны, акцент — сдержанный синий `#0071e3` (`#0a84ff` в тёмной). Пилот: дашборд + заказы → согласование → остальные страницы.

**Сделано:**
- `base.css`: полностью переписан `:root` и `body.theme-dark` (палитра Apple HIG: `#f5f5f7`/`#1d1d1f`/`#6e6e73`, статусы `#34c759`/`#ff3b30`/`#ff9500`; тёмная `#000000`/`#1c1c1e`), `--radius:20px`, `--radius-sm:12px`, Inter вместо Fraunces.
- Стекло: `.top-bar`/`.bottom-nav` — `rgba(255,255,255,.72)` + `saturate(180%) blur(20px)` (тёмная: `rgba(0,0,0,.72)` + граница `rgba(255,255,255,.10)`).
- `body` — плоский `#f5f5f7` (убран teal-градиент); `.hero-card`, `.metric-card.accent`, `.badge-progress`, `.tab-btn` (сегменты: активный `--text`), `.btn` (0.3s ease), `.modal` (blur+24px), `.search-box .form-control`, `.thumb`, `.skeleton-row`, `.kanban-column`, desktop-отступы.
- `.stat-card`: радиус `var(--radius)`, padding 18/20; `.stat-icon.purple` → монохром `--secondary-soft`.
- Хардкоды → токены: `chat.css` (`#e5484d`→`--danger`, градиент `#1d7e91`→primary-градиент), `ux.css` (login `#0D6E7E`→`--primary`), `enhance.css` focus `#197387`→`#0071e3`, инлайн `1px solid #efeff4` → `var(--border)` (6 компонентов).
- Chart.js (дашборд): `#197387`/`#3d8662` → `#0071e3`/`#34c759`; donut-палитра `ui.js` → Apple system colors (светлая гамма).
- `base.html`: шрифт-ссылка без Fraunces, `theme-color` `#0071e3`.
- Кнопки → капсулы (980px, 40px/34px sm), поля форм → iOS filled (rgba(118,118,128,.12), radius 10), фокус → Apple-гало 3px, `.icon-btn` → круг 36px, цифры → `tabular-nums`.
- Сайдбар → стекло (blur 20px), выбор активного → macOS-серый `rgba(0,0,0,.07)` (тёмная: `rgba(255,255,255,.12)`), desktop hero 32px/36px + h2 32px, входная анимация страниц, hover-lift карточек.

**Проверено (DOM/вычисленные стили, светлая+тёмная):** фон/карточки/бордеры/радиусы/стекло/активный таб — соответствуют токенам; donut `#0071e3`; консоль без ошибок на дашборде и заказах; `node --check` всех компонентов OK.

**Скриншоты для визуального ревью:** `C:\Users\User\AppData\Local\Temp\opencode\shot_{dashboard,orders}_{light,dark}.png`

**Осталось:** ~~визуальное ревью пользователем → перенос на остальные страницы~~; ✅ полный прогон тестов закрыт (825 OK, 2026-08-11).

## 12. Удобство (UX для «человека с улицы», 2026-08-11)

- Пустые состояния → CTA-кнопки: заказы «Создать заказ», склад «Добавить материал», клиенты «Добавить клиента», продукция «Добавить продукт» (кнопка рендерится как `btn btn-primary btn-sm`, срабатывает `openForm()`; `listStates.empty()` теперь рисует действие кнопкой, а не текстом).
- Футер: убраны «Built by…/Coming soon…» → скромное «© 2026 · Версия 2.0» (ключ `footer.version` во всех локалях).
- Уже было (подтверждено): язык сохраняется в localStorage (i18n.js:12), автофокус в модалках (ui.js:91), скелетоны/gone/retry во всех списках, тач-цели ≥44px.
- i18n-тесты: 4/4 OK после правки локалей.

## 10. Как проверять изменения

- `python manage.py test apps.core.tests_i18n_keys_k` — i18n
- `python manage.py test` — полный прогон (823 теста)
- Ручная проверка: owner (финансы/аналитика с периодами), admin (редактирование), manager (без денег), worker (мобильный вид, канбан, чат)
