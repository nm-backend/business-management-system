# SkladPro.Nod — Docker Quick Start (для Нодирбека)

Пошаговая инструкция «с нуля». Предполагается, что ты **никогда не запускал этот
проект** и, возможно, впервые работаешь с Docker.

Хорошая новость: **Python, PostgreSQL и Redis ставить вручную НЕ нужно.**
Docker поднимет всё сам. Твоя задача — выполнить команды по порядку.

---

## 1. Требования (установить один раз)

### 1.1. Git
Скачай и установи: https://git-scm.com/downloads
(жми «Next» со значениями по умолчанию).

Проверка — открой терминал (Windows: **PowerShell**; macOS/Linux: **Terminal**):
```bash
git --version
```
Должна появиться версия, например `git version 2.45.1`.

### 1.2. Docker Desktop
Скачай: https://www.docker.com/products/docker-desktop

- **Windows:** запусти установщик. Обязательно оставь галочку
  **«Use WSL 2 instead of Hyper-V»**. После установки **перезагрузи компьютер**.
- **macOS:** выбери версию под свой чип (Apple Silicon или Intel), перетащи в Applications.
- **Linux:** ставь Docker Engine + Compose plugin: https://docs.docker.com/engine/install/

### 1.3. WSL2 (только Windows)
Docker Desktop обычно включает WSL2 сам. Если он попросит — согласись.
Если появилась ошибка про WSL, открой PowerShell **от имени администратора** и выполни:
```powershell
wsl --install
wsl --update
```
Затем перезагрузи компьютер.

### 1.4. Виртуализация (только Windows, если Docker ругается)
Если Docker пишет *«Virtualization is not enabled»*:
1. Открой «Диспетчер задач» → вкладка **«Производительность»** → **ЦП**.
2. Посмотри строку **«Виртуализация»**. Если написано **«Отключено»** —
   нужно включить её в BIOS/UEFI.
3. Перезагрузи ПК → зайди в BIOS (обычно клавиша `Del`, `F2` или `F10` при включении) →
   найди пункт **Intel VT-x / AMD-V / SVM Mode** → **Enable** → сохрани и выйди.

### 1.5. Проверка, что Docker работает
**Сначала запусти приложение Docker Desktop** и дождись, пока значок кита
перестанет мигать, а статус станет **«Engine running»** (зелёный).

Затем в терминале:
```bash
docker --version
docker compose version
docker info
```
- Первые две команды покажут версии.
- `docker info` должна показать строку **Server Version** (значит движок доступен).

> ❗ Если видишь `Cannot connect to the Docker daemon` или
> `failed to connect to the docker API` — **Docker Desktop не запущен**.
> Открой его и подожди 1–2 минуты. Пока движок не запущен, ничего работать не будет.

---

## 2. Клонировать проект

```bash
git clone <URL-репозитория>
cd business-management-system
```

Все команды ниже выполняются **из этой папки** (там, где лежит `docker-compose.yml`).

---

## 3. Окружение (.env)

- **`.env.docker.example`** — файл-пример со списком переменных.
- **`.env`** — твой личный файл с настройками (в git не попадает).

**Самое важное: для локального запуска `.env` создавать НЕ обязательно.**
Все значения по умолчанию уже прописаны в `docker-compose.yml`, проект
запустится «как есть». Просто переходи к шагу 4.

Если всё же хочешь свои значения:
```powershell
# Windows
copy .env.docker.example .env
```
```bash
# macOS / Linux
cp .env.docker.example .env
```

| Переменная | Менять? | Комментарий |
|---|---|---|
| `SECRET_KEY` | для локальной работы — не обязательно; **для сервера — обязательно** | длинная случайная строка |
| `DEBUG` | оставь `True` локально; на сервере `False` | режим отладки |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD` | можно оставить по умолчанию | логин/пароль базы |
| `ALLOWED_HOSTS` | локально не трогай | разрешённые адреса |
| `DB_HOST`, `DB_PORT`, `REDIS_URL` | **не трогай** | внутри Docker это `db` и `redis` |

---

## 4. Запустить проект

Одна команда:

```bash
docker compose up --build
```

Что произойдёт автоматически (ничего вручную делать не нужно):
1. **PostgreSQL** (контейнер `db`) — скачается и запустится база данных.
2. **Redis** (контейнер `redis`) — запустится (нужен для чата/WebSocket).
3. **Django** (контейнер `web`) — соберётся образ и запустится сервер.
4. **Миграции** применятся автоматически при старте (`manage.py migrate`).
5. **Статика** соберётся автоматически (`manage.py collectstatic`).

Первый запуск идёт **несколько минут** (скачивание образов + установка зависимостей).
Это нормально. Следующие запуски — быстрые.

Когда в логах увидишь строку:
```
Listening on TCP address 0.0.0.0:8000
```
— сервер готов. 🎉

> Совет: чтобы запустить в фоне (терминал освободится), добавь `-d`:
> ```bash
> docker compose up --build -d
> ```
> Смотреть логи потом: `docker compose logs -f web`

---

## 5. Проверить контейнеры

```bash
docker ps
```
или (удобнее):
```bash
docker compose ps
```

Ты должен увидеть **три контейнера**:

| Сервис | Что это | Ожидаемый статус |
|---|---|---|
| `...-web-1` | Django-приложение | `Up` |
| `...-db-1` | PostgreSQL | `Up (healthy)` |
| `...-redis-1` | Redis | `Up (healthy)` |

Если какого-то нет или он `Restarting` — смотри раздел **10. Troubleshooting**.

---

## 6. Открыть проект в браузере

| Что | Адрес |
|---|---|
| Приложение | http://127.0.0.1:8000 |
| Django Admin | http://127.0.0.1:8000/admin/ |
| Swagger (API) | **http://127.0.0.1:8000/api/v1/swagger/** |
| ReDoc (API) | **http://127.0.0.1:8000/api/v1/redoc/** |

> ⚠️ **Важно:** Swagger и ReDoc находятся по адресам с префиксом **`/api/v1/`**.
> Просто `/swagger/` и `/redoc/` вернут **404** — это не ошибка проекта.

---

## 7. Вход в админку (создать супер-администратора)

При первом запуске база пустая — админов ещё нет. Создай супер-администратора.

**Контейнеры должны быть запущены** (шаг 4). Открой **второй терминал** в той же папке:

```bash
docker compose exec web python manage.py createsuperuser
```

Введи:
- **Username** — например `admin`
- **Email** — можно оставить пустым (просто Enter)
- **Password** — минимум 8 символов, не слишком простой (при вводе символы не отображаются — это нормально)

Затем открой http://127.0.0.1:8000/admin/ и войди.

**Дальше рабочий процесс такой:**
`Admin → Companies → Add company` (компания + владелец за один шаг) →
открыть компанию → кнопка **«+ Добавить сотрудника»** → система сама выдаст
**Access Key** (`SKP-XXXX-XXXX-XXXX`) → скопируй его и отдай сотруднику.
Сотрудник вводит код на странице входа и задаёт себе пароль.

> Забыл пароль админа?
> `docker compose exec web python manage.py changepassword admin`

---

## 8. Остановить проект

```bash
docker compose down
```
Контейнеры остановятся, **но все данные сохранятся** (база, файлы).
Следующий запуск: `docker compose up -d` — и всё на месте.

```bash
docker compose down -v
```
То же самое, **НО удалит тома (volumes)** — то есть **сотрёт базу данных**:
компании, сотрудники, заказы, супер-админ — всё исчезнет.

| Команда | Данные |
|---|---|
| `docker compose down` | ✅ сохраняются |
| `docker compose down -v` | ❌ **удаляются безвозвратно** |

Используй `-v` только когда хочешь начать **с чистого листа**.

---

## 9. Обновить проект (когда появились новые изменения)

```bash
git pull
docker compose up --build -d
```

Миграции применятся автоматически при старте. Если хочешь применить вручную:
```bash
docker compose exec web python manage.py migrate
```

Если менялись базовые образы:
```bash
docker compose pull      # обновить postgres/redis
docker compose build     # пересобрать приложение
docker compose up -d     # перезапустить
```

> Изменил код, но в браузере ничего не поменялось?
> `docker compose restart web` (сервер перечитает код).

---

## 10. Troubleshooting (частые проблемы)

### ❌ Docker Desktop не запущен
**Симптом:** `Cannot connect to the Docker daemon` / `failed to connect to the docker API ... dockerDesktopLinuxEngine`.
**Решение:** открой приложение **Docker Desktop**, дождись статуса «Engine running» (1–2 минуты), повтори команду.

### ❌ Порт 8000 уже занят
**Симптом:** `port is already allocated` или `address already in use`.
**Решение 1** — найти и закрыть процесс:
```powershell
# Windows
netstat -ano | findstr :8000
taskkill /PID <номер_PID> /F
```
```bash
# macOS / Linux
lsof -i :8000
kill -9 <PID>
```
**Решение 2** — запустить на другом порту: в `docker-compose.yml` у сервиса `web` поменяй
`"8000:8000"` на `"8001:8000"`, затем `docker compose up -d`. Открывать: http://127.0.0.1:8001

### ❌ PostgreSQL не стартует
**Симптом:** контейнер `db` не становится `healthy`; в логах ошибки БД.
**Решение:**
```bash
docker compose logs db          # посмотреть причину
docker compose down -v          # пересоздать том (⚠️ удалит данные)
docker compose up --build
```

### ❌ Redis не стартует
**Симптом:** `redis` не `healthy`; чат не работает в реальном времени.
**Решение:**
```bash
docker compose logs redis
docker compose restart redis
```

### ❌ Контейнеры постоянно перезапускаются (`Restarting`)
**Решение:** смотри причину — она почти всегда в логах:
```bash
docker compose logs web
```
Частые причины: опечатка в `.env`, недоступная БД, ошибка в коде.
Быстрый сброс: `docker compose down && docker compose up --build`.

### ❌ Проблемы с WSL2 (Windows)
**Симптом:** `WSL 2 installation is incomplete`, `wsl.exe not found`.
**Решение:** PowerShell **от администратора**:
```powershell
wsl --install
wsl --update
wsl --set-default-version 2
```
Затем перезагрузи ПК и запусти Docker Desktop.

### ❌ Build failed (сборка упала)
**Решение:** чаще всего это временный сбой сети при скачивании пакетов.
```bash
docker compose build --no-cache
docker compose up
```
Если не помогло — скопируй **последние 20 строк ошибки** и покажи разработчику.

### ❌ Migration failed
**Симптом:** в логах `django.db.utils.ProgrammingError` / `relation ... does not exist`.
**Решение:**
```bash
docker compose exec web python manage.py migrate     # попробовать ещё раз
```
Если база «сломалась» и данные не жалко — чистый старт:
```bash
docker compose down -v
docker compose up --build
```

### 🔎 Универсальный совет
Почти всегда причина видна здесь:
```bash
docker compose logs web
docker compose ps
```
Скопируй вывод и покажи разработчику — этого достаточно для диагностики.

---

## 11. Чек-лист «всё получилось»

- [ ] `docker info` показывает **Server Version** (движок запущен)
- [ ] `docker compose ps` → три контейнера: `web` (Up), `db` (healthy), `redis` (healthy)
- [ ] http://127.0.0.1:8000 — открывается приложение
- [ ] http://127.0.0.1:8000/admin/ — открывается админка, вход работает
- [ ] http://127.0.0.1:8000/api/v1/swagger/ — открывается Swagger
- [ ] http://127.0.0.1:8000/api/v1/redoc/ — открывается ReDoc
- [ ] Создал компанию → добавил сотрудника → получил Access Key `SKP-XXXX-XXXX-XXXX`

Если все пункты отмечены — проект запущен полностью. Удачи, Нодирбек! 🚀
