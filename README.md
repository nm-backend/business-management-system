# SkladPro.Nod — ERP

**RU:** Система управления производством: склад, заказы, производство, финансы, клиенты, сотрудники и чат в реальном времени.
**UZ:** Ишлаб чиқаришни бошқариш тизими: омбор, буюртмалар, ишлаб чиқариш, молия, мижозлар, ходимлар ва реал вақтли чат.

> **RU:** Этот файл — единственная инструкция. Читай сверху вниз, ничего не пропускай.
> **UZ:** Бу файл — ягона қўлланма. Юқоридан пастга қараб ўқинг, ҳеч нарсани ташлаб кетманг.

---

# ⚡ Самое быстрое / Энг тез усул

**RU:** Если Docker уже установлен — всего 2 команды:
**UZ:** Агар Docker ўрнатилган бўлса — бор-йўғи 2 та буйруқ:

```bash
docker compose up --build
```
```bash
docker compose exec web python manage.py createsuperuser
```

**RU:** Открой → http://127.0.0.1:8000
**UZ:** Очинг → http://127.0.0.1:8000

**RU:** Не установлен Docker? Читай раздел для своей системы ниже.
**UZ:** Docker йўқми? Пастдаги ўз тизимингиз учун бўлимни ўқинг.

---

# 🍎 macOS — с нуля / Ноldan бошлаб

**RU:** Терминал: `Cmd + Пробел` → напиши `Terminal` → Enter.
**UZ:** Терминал: `Cmd + Пробел` → `Terminal` деб ёзинг → Enter.

### 1. Homebrew

**RU:** Это установщик программ для Mac. Вставь в терминал и нажми Enter:
**UZ:** Бу Mac учун дастур ўрнатувчи. Терминалга қўйинг ва Enter босинг:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

**RU:** Попросит пароль от Mac — вводи (символы не видны, это нормально), Enter.
**UZ:** Mac паролини сўрайди — киритинг (белгилар кўринмайди, бу нормал), Enter.

**RU:** Если Mac на Apple Silicon (M1/M2/M3), выполни ещё это:
**UZ:** Агар Mac Apple Silicon (M1/M2/M3) бўлса, буни ҳам бажаринг:

```bash
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
```
```bash
eval "$(/opt/homebrew/bin/brew shellenv)"
```

**RU:** Проверка / **UZ:** Текшириш:
```bash
brew --version
```

### 2. Git

```bash
brew install git
```
```bash
git --version
```

### 3. Docker Desktop

```bash
brew install --cask docker
```

**RU:** ⚠️ Дальше ОБЯЗАТЕЛЬНО: открой Launchpad → запусти **Docker** → согласись с условиями → жди, пока кит 🐳 вверху экрана перестанет мигать.
**UZ:** ⚠️ Кейин МАЖБУРИЙ: Launchpad → **Docker** ни ишга туширинг → шартларга розилик беринг → экран тепасидаги кит 🐳 липиллашдан тўхтагунча кутинг.

**RU:** Проверка (обе команды должны показать версии):
**UZ:** Текшириш (иккала буйруқ ҳам версия кўрсатиши керак):
```bash
docker --version
```
```bash
docker compose version
```

### 4. VS Code (RU: необязательно / UZ: шарт эмас)

```bash
brew install --cask visual-studio-code
```

### 5. Скачать проект / Лойиҳани юклаш

```bash
cd ~/Desktop
```
```bash
git clone <URL-РЕПОЗИТОРИЯ>
```
```bash
cd business-management-system
```

**RU:** `<URL-РЕПОЗИТОРИЯ>` — ссылка, которую даст владелец проекта.
**UZ:** `<URL-РЕПОЗИТОРИЯ>` — лойиҳа эгаси берадиган ҳавола.

### 6. Запуск / Ишга тушириш

```bash
docker compose up --build
```

**RU:** Первый раз — 5–10 минут. Жди строку `Listening on TCP address 0.0.0.0:8000`.
**UZ:** Биринчи марта — 5–10 дақиқа. `Listening on TCP address 0.0.0.0:8000` қаторини кутинг.

**RU:** Открой браузер → http://127.0.0.1:8000
**UZ:** Браузерни очинг → http://127.0.0.1:8000

**RU:** ⚠️ Терминал НЕ закрывай — сервер работает в нём.
**UZ:** ⚠️ Терминални ЁПМАНГ — сервер унда ишлаяпти.

### 7. Создать админа / Админ яратиш

**RU:** Открой **ВТОРОЙ** терминал (`Cmd + T`), в той же папке:
**UZ:** **ИККИНЧИ** терминал очинг (`Cmd + T`), ўша папкада:

```bash
cd ~/Desktop/business-management-system
```
```bash
docker compose exec web python manage.py createsuperuser
```

**RU:** Введи логин, email (можно пропустить — Enter), пароль (минимум 8 символов; при вводе не видно — это нормально).
**UZ:** Логин, email (ўтказиб юборса бўлади — Enter), парол киритинг (камида 8 белги; ёзганда кўринмайди — бу нормал).

---

# 🪟 Windows — с нуля / Ноldan бошлаб

**RU:** Терминал: кнопка «Пуск» → напиши `PowerShell` → Enter.
**UZ:** Терминал: «Пуск» тугмаси → `PowerShell` деб ёзинг → Enter.

### 1. Git
**RU:** Скачай и установи (жми «Next» везде): https://git-scm.com/downloads
**UZ:** Юклаб ўрнатинг (ҳамма жойда «Next»): https://git-scm.com/downloads

```powershell
git --version
```

### 2. Docker Desktop
**RU:** Скачай: https://www.docker.com/products/docker-desktop
При установке оставь галочку **WSL 2**. После установки — **перезагрузи компьютер**.
**UZ:** Юклаб олинг: https://www.docker.com/products/docker-desktop
Ўрнатишда **WSL 2** белгисини қолдиринг. Ўрнатгач — **компьютерни қайта юкланг**.

**RU:** Потом запусти **Docker Desktop** и жди статус **Engine running**.
**UZ:** Кейин **Docker Desktop** ни ишга туширинг ва **Engine running** ҳолатини кутинг.

```powershell
docker --version
```
```powershell
docker compose version
```

**RU:** Ошибка про WSL? PowerShell **от имени администратора**:
**UZ:** WSL хатоси чиқдими? PowerShell **администратор номидан**:
```powershell
wsl --install
```
```powershell
wsl --update
```
**RU:** Затем перезагрузи ПК. / **UZ:** Кейин компьютерни қайта юкланг.

### 3. VS Code (RU: необязательно / UZ: шарт эмас)
https://code.visualstudio.com/download

### 4. Скачать проект / Лойиҳани юклаш

```powershell
cd $HOME\Desktop
```
```powershell
git clone <URL-РЕПОЗИТОРИЯ>
```
```powershell
cd business-management-system
```

### 5. Запуск / Ишга тушириш

```powershell
docker compose up --build
```

**RU:** Открой → http://127.0.0.1:8000 | **UZ:** Очинг → http://127.0.0.1:8000

### 6. Создать админа / Админ яратиш

**RU:** Второй PowerShell, в той же папке:
**UZ:** Иккинчи PowerShell, ўша папкада:

```powershell
cd $HOME\Desktop\business-management-system
```
```powershell
docker compose exec web python manage.py createsuperuser
```

---

# 🔗 Адреса / Ҳаволалар

| RU | UZ | URL |
|---|---|---|
| Сайт | Сайт | http://127.0.0.1:8000 |
| Админка | Админ панел | http://127.0.0.1:8000/admin/ |
| Swagger (API) | Swagger (API) | http://127.0.0.1:8000/api/v1/swagger/ |
| ReDoc (API) | ReDoc (API) | http://127.0.0.1:8000/api/v1/redoc/ |

> **RU:** ⚠️ Swagger и ReDoc **только** с префиксом `/api/v1/`. Просто `/swagger/` даст ошибку 404 — это не поломка.
> **UZ:** ⚠️ Swagger ва ReDoc **фақат** `/api/v1/` префикси билан. Оддий `/swagger/` 404 хато беради — бу носозлик эмас.

---

# 👥 Как работает система / Тизим қандай ишлайди

**RU:** Обычной регистрации НЕТ. Сотрудник входит по коду доступа (Access Key).
**UZ:** Оддий рўйхатдан ўтиш ЙЎҚ. Ходим кириш коди (Access Key) орқали киради.

```
Админ → Компании → выбрать компанию → «+ Добавить сотрудника»
      → система выдаёт код SKP-XXXX-XXXX-XXXX → отдать сотруднику
Сотрудник → страница входа → «У меня есть код доступа» → вводит код
      → задаёт свой пароль → вошёл
```

**RU:** Порядок в админке:
1. `Компании` → `Добавить` — создаётся компания + её владелец сразу.
2. Открыть компанию → кнопка **«+ Добавить сотрудника»**.
3. Заполнить форму → система покажет **код доступа** и кнопку «Копировать».
4. Отдать код сотруднику.

**UZ:** Админ панелдаги тартиб:
1. `Компании` → `Добавить` — компания ва унинг эгаси бирдан яратилади.
2. Компанияни очинг → **«+ Добавить сотрудника»** тугмаси.
3. Формани тўлдиринг → тизим **кириш кодини** ва «Копировать» тугмасини кўрсатади.
4. Кодни ходимга беринг.

**RU:** Код одноразовый. Отозвать/перевыпустить: `Сотрудники и доступы → Коды доступа`.
**UZ:** Код бир марталик. Бекор қилиш/қайта чиқариш: `Сотрудники и доступы → Коды доступа`.

---

# 🛠 Команды на каждый день / Кундалик буйруқлар

```bash
docker compose up -d          # RU: запустить в фоне    | UZ: фонда ишга тушириш
docker compose ps             # RU: статус контейнеров  | UZ: контейнерлар ҳолати
docker compose logs -f web    # RU: логи (ошибки)       | UZ: логлар (хатолар)
docker compose restart web    # RU: перезапуск          | UZ: қайта ишга тушириш
docker compose down           # RU: стоп (данные целы)  | UZ: тўхтатиш (маълумот сақланади)
docker compose down -v        # RU: стоп + УДАЛИТЬ БД!  | UZ: тўхтатиш + БАЗАНИ ЎЧИРИШ!
```

> **RU:** ⚠️ `down -v` удаляет базу навсегда: компании, сотрудников, заказы. Без `-v` — данные сохраняются.
> **UZ:** ⚠️ `down -v` базани бутунлай ўчиради: компаниялар, ходимлар, буюртмалар. `-v` сиз — маълумот сақланади.

**RU:** Обновить проект / **UZ:** Лойиҳани янгилаш:
```bash
git pull
```
```bash
docker compose up --build -d
```

---

# 🚑 Если не работает / Ишламаса

| RU: Проблема | UZ: Муаммо | RU: Решение / UZ: Ечим |
|---|---|---|
| `Cannot connect to the Docker daemon` | Docker уланмаяпти | RU: Docker Desktop не запущен — открой его, жди 1–2 мин. UZ: Docker Desktop ишламаяпти — очинг, 1–2 дақиқа кутинг. |
| `port is already allocated` | Порт банд | RU: Порт 8000 занят. В `docker-compose.yml` замени `"8000:8000"` на `"8001:8000"`, открывай :8001. UZ: 8000-порт банд. `docker-compose.yml` да `"8000:8000"` ни `"8001:8000"` га алмаштиринг, :8001 ни очинг. |
| RU: Контейнер перезапускается | UZ: Контейнер қайта ишга тушаверади | `docker compose logs web` — RU: причина видна там. UZ: сабаб ўша ерда кўринади. |
| RU: Изменил код — нет эффекта | UZ: Код ўзгарди — натижа йўқ | `docker compose restart web` |
| RU: Нет стилей / UZ: Стиллар йўқ | | `docker compose restart web` |
| RU: Чат не обновляется | UZ: Чат янгиланмаяпти | RU: Проверь `docker compose ps` — `redis` должен быть healthy. UZ: `docker compose ps` — `redis` healthy бўлиши керак. |
| RU: Забыл пароль админа | UZ: Админ паролини унутдим | `docker compose exec web python manage.py changepassword <логин>` |
| RU: Хочу начать заново | UZ: Бошидан бошлашни хоҳлайман | `docker compose down -v` → `docker compose up --build` |

**RU:** Не помогло? Скопируй вывод `docker compose logs web` и отправь разработчику — там всегда видна причина.
**UZ:** Ёрдам бермадими? `docker compose logs web` натижасини нусхалаб дастурчига юборинг — сабаб доим ўша ерда кўринади.

---

# ✅ Проверка / Текшириш

- [ ] `docker compose ps` → RU: 3 контейнера: `web` (Up), `db` (healthy), `redis` (healthy) | UZ: 3 та контейнер
- [ ] http://127.0.0.1:8000 — RU: сайт открылся | UZ: сайт очилди
- [ ] http://127.0.0.1:8000/admin/ — RU: вход работает | UZ: кириш ишлаяпти
- [ ] http://127.0.0.1:8000/api/v1/swagger/ — RU: Swagger открылся | UZ: Swagger очилди
- [ ] RU: Создал компанию → сотрудника → получил код `SKP-...` | UZ: Компания → ходим → `SKP-...` коди олинди

---

# 🧰 Технологии / Технологиялар

Django 5.1 · Django REST Framework · JWT · Channels (WebSocket) · PostgreSQL 16 · Redis 7 · Daphne (ASGI) · WhiteNoise · Docker

**RU:** Frontend — обычный JavaScript, сборка (Node.js/npm) НЕ нужна.
**UZ:** Frontend — оддий JavaScript, сборка (Node.js/npm) КЕРАК ЭМАС.

---

# ⚙️ Переменные окружения / Муҳит ўзгарувчилари

**RU:** Для локального Docker `.env` создавать НЕ нужно — значения по умолчанию уже в `docker-compose.yml`.
**UZ:** Локал Docker учун `.env` яратиш ШАРТ ЭМАС — стандарт қийматлар `docker-compose.yml` да бор.

**RU:** Нужны свои значения? Скопируй пример: / **UZ:** Ўз қийматларингиз керакми? Намунадан нусха олинг:
```bash
cp .env.docker.example .env      # macOS/Linux
```
```powershell
copy .env.docker.example .env    # Windows
```

| RU: Переменная | RU: Назначение / UZ: Вазифаси |
|---|---|
| `SECRET_KEY` | RU: Ключ Django. **Для интернета — обязательно заменить!** UZ: Django калити. **Интернет учун — мажбурий алмаштиринг!** |
| `DEBUG` | RU: `True` локально, `False` в интернете. UZ: Локал `True`, интернетда `False`. |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` | RU: Данные БД. UZ: Базa маълумотлари. |
| `ALLOWED_HOSTS` | RU: Разрешённые адреса. UZ: Рухсат этилган манзиллар. |

**RU:** `DB_HOST=db` и `REDIS_URL=redis://redis:6379/0` внутри Docker менять НЕ нужно.
**UZ:** Docker ичида `DB_HOST=db` ва `REDIS_URL=redis://redis:6379/0` ни ЎЗГАРТИРМАНГ.

---

# 🧪 Тесты / Тестлар

```bash
docker compose exec -e DJANGO_SETTINGS_MODULE=skladpro.test_settings web python manage.py test
```
**RU:** Должно быть `OK`. / **UZ:** `OK` бўлиши керак.

---

# 💻 Без Docker (RU: только для разработчиков / UZ: фақат дастурчилар учун)

**RU:** Нужны Python 3.11+ и PostgreSQL, установленные вручную. Docker проще — используй его.
**UZ:** Қўлда ўрнатилган Python 3.11+ ва PostgreSQL керак. Docker осонроқ — ундан фойдаланинг.

```bash
python -m venv venv
```
```bash
source venv/bin/activate      # macOS/Linux
```
```powershell
venv\Scripts\Activate.ps1     # Windows
```
```bash
pip install -r requirements.txt
```
**RU:** Создай `.env` (см. `.env.docker.example`), укажи `DB_HOST=localhost`, создай базу в PostgreSQL, затем:
**UZ:** `.env` яратинг (`.env.docker.example` га қаранг), `DB_HOST=localhost` ёзинг, PostgreSQL да база яратинг, кейин:
```bash
python manage.py migrate
```
```bash
python manage.py createsuperuser
```
```bash
python manage.py runserver
```

---

# 🚀 Деплой в интернет / Интернетга жойлаштириш

**RU:** Проект готов к Render — единственной production-платформе (Railway больше
не используется; `railway.toml` удалён). Вся инфраструктура — в `render.yaml`:
Render → New → Blueprint → выбрать `render.yaml`.
**UZ:** Такимиратув саҚлиқ — Render (`railway.toml` ўчирилган). Инфраструктура
`render.yaml`да: Render → New → Blueprint → `render.yaml`.

1. **RU:** Environment Group `skladpro-secrets` → + `SECRET_KEY` (длинный случайный).
   Ключ яратиш:
   ```bash
   python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
   ```
   **UZ:** `skladpro-secrets` → `SECRET_KEY`.
2. **RU:** Render → New → Blueprint → `render.yaml`. Render создаст: Web Service
   (Daphne/ASGI, `$PORT` через Dockerfile), PostgreSQL (`skladpro-db`), Redis
   (`skladpro-redis`), Celery Worker (`skladpro-worker`) и Celery Beat
   (`skladpro-beat`). `SKIP_INIT=1` у воркера/бита — миграции, статика и
   супер-админ применяются входом web через `docker/entrypoint.sh`.
   **UZ:** Blueprint → `render.yaml`. Web (Daphne), PostgreSQL, Redis, Worker, Beat.
3. **RU:** Чтобы войти в `/admin/`, один раз задайте в Environment Group
   `DJANGO_SUPERUSER_USERNAME` + `DJANGO_SUPERUSER_PASSWORD` (читает
   `ensure_superuser` из entrypoint); либо `/accounts/setup/` после старта.
   **UZ:** `/admin/` учун `DJANGO_SUPERUSER_USERNAME` ва `DJANGO_SUPERUSER_PASSWORD`.
4. **RU:** ⚠️ Обычный gunicorn НЕ обслужит WebSocket — чат работать не будет.
   Запуск через Daphne в Dockerfile (уже настроен, `$PORT` подставляет Render).
   **UZ:** ⚠️ gunicorn WebSocket ни қўллаб-қувватламайди. Daphne (Dockerfile).
5. **RU:** Медиа (фото работ/материалов/готовой продукции, аватары) хранится на
   эфемерном filesystem Render — после redeploy исчезнут. Чтобы сохранять фото,
   включите S3/R2: задайте credentials в Environment Group (см. закомментированные
   строки в `render.yaml`): `AWS_STORAGE_BUCKET_NAME`, `AWS_ACCESS_KEY_ID`,
   `AWS_SECRET_ACCESS_KEY`, `AWS_S3_ENDPOINT_URL`, `AWS_S3_REGION_NAME`.
   **UZ:** Медиа эфемер; S3/R2 уйимлаштиринг (render.yaml шартлари).

---

# ❓ FAQ

**RU: Нужно ли ставить Python/PostgreSQL/Redis отдельно?**
Нет. Docker ставит всё сам.
**UZ: Python/PostgreSQL/Redis ни алоҳида ўрнатиш керакми?**
Йўқ. Docker ҳаммасини ўзи ўрнатади.

**RU: Почему первый запуск такой долгий?**
Скачиваются образы и ставятся зависимости. Дальше — быстро.
**UZ: Нега биринчи ишга тушириш узоқ?**
Образлар юкланади ва кутубхоналар ўрнатилади. Кейингилари тез.

**RU: Можно закрыть терминал?**
Только если запускал с `-d`. Иначе сервер остановится.
**UZ: Терминални ёпса бўладими?**
Фақат `-d` билан ишга туширган бўлсангиз. Акс ҳолда сервер тўхтайди.

**RU: Данные пропадут после `docker compose down`?**
Нет. Пропадут только после `down -v`.
**UZ: `docker compose down` дан кейин маълумот йўқоладими?**
Йўқ. Фақат `down -v` дан кейин йўқолади.
