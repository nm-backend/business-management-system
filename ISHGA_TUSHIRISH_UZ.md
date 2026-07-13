# SkladPro.Nod — Серверни нолдан ишга тушириш қўлланмаси

> Ассалому алайкум! Бу қўлланма бўйича лойиҳани ўз компьютерингда босқичма-босқич
> ишга туширасан. Ҳар бир буйруқни айнан кўрсатилгандай ёз. Кодлар инглизча бўлади
> (улар — буйруқлар, ўзгартириб бўлмайди), тушунтиришлар ўзбекча.
>
> Қўлланмадаги ҳар бир қадам лойиҳани ҳақиқатан нолдан қайта ишга тушириб текширилган.

---

## 1. Керакли дастурлар (аввал ўрнат)

Бошлашдан олдин компьютерингга шуларни ўрнат:

| Дастур | Версия | Изоҳ |
|--------|--------|------|
| **Python** | 3.11 ёки янгироқ (3.13 текширилган) | python.org сайтидан юклаб ол. Ўрнатишда **«Add Python to PATH»** белгисини албатта белгила! |
| **PostgreSQL** | 14 ёки янгироқ (18 текширилган) | postgresql.org сайтидан. Ўрнатишда `postgres` фойдаланувчиси учун **паролни ёзиб қўй** — кейин керак бўлади. |
| **GitHub Desktop** | сўнгги версия | desktop.github.com сайтидан. |

> **Node.js / npm КЕРАК ЭМАС.** Сайтнинг фронтенд қисми оддий JavaScript'да
> ёзилган, «сборка» қадами йўқ.

---

## 2. GitHub Desktop орқали лойиҳани юклаб олиш

1. GitHub Desktop'ни оч.
2. Юқоридан **`File → Clone repository…`** ни танла.
3. Рўйхатдан лойиҳани (`business-management-system`) танла ёки унинг URL'ини ёз.
4. **«Local path»** — лойиҳа қаерга сақланишини кўрсат
   (масалан `C:\Users\СенингИсминг\Documents\GitHub`).
5. **`Clone`** тугмасини бос ва кутиб тур.

Юклаб бўлгач, шу ойнанинг ўзида **`Repository → Open in Command Prompt`**
(ёки PowerShell) ни танла — терминал очилади ва лойиҳа папкасида турибди.
Кейинги ҳамма буйруқни шу терминалда ёзасан.

---

## 3. Виртуал муҳит (venv) яратиш

Лойиҳа папкасида турган ҳолда буйруқларни кетма-кет ёз:

```powershell
python -m venv venv
```

Кейин уни фаоллаштир (PowerShell учун):

```powershell
venv\Scripts\Activate.ps1
```

Тўғри бўлса, қатор бошида **`(venv)`** ёзуви пайдо бўлади.

> ⚠️ Агар PowerShell «скриптларни бажариш ўчирилган» деб хато берса, аввал шуни ёз:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```
> Кейин яна `venv\Scripts\Activate.ps1` ни ёз.
>
> Агар `cmd.exe`дан фойдалансанг, фаоллаштириш буйруғи бошқача:
> `venv\Scripts\activate.bat`

---

## 4. Кутубхоналарни ўрнатиш

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Бу буйруқ Django ва барча керакли кутубхоналарни ўрнатади. Хатосиз тугаши керак.

---

## 5. PostgreSQL — маълумотлар базасини созлаш

Аввал `psql` дастурини оч (Windows'да одатда шу жойда бўлади):

```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres
```

`postgres` фойдаланувчисининг паролини сўрайди (уни PostgreSQL ўрнатганингда ёзгансан).

Очилгач, шу буйруқларни ёз (база ва фойдаланувчи яратамиз):

```sql
CREATE USER skladpro_user WITH PASSWORD 'kuchli_parol';
CREATE DATABASE skladpro_db OWNER skladpro_user ENCODING 'UTF8';
GRANT ALL PRIVILEGES ON DATABASE skladpro_db TO skladpro_user;
\c skladpro_db
GRANT ALL ON SCHEMA public TO skladpro_user;
\q
```

> - `\q` — psql'дан чиқиш.
> - `'kuchli_parol'` ўрнига ўзинг ўйлаб топган кучли парол ёз ва **эсда сақла** —
>   6-қадамда керак бўлади.
> - `GRANT ALL ON SCHEMA public...` — PostgreSQL 15 ва ундан юқорисида шарт,
>   акс ҳолда `migrate` «permission denied for schema public» хатосини беради.
>
> **Осон вариант:** янги фойдаланувчи яратмасдан, тайёр `postgres`
> фойдаланувчисидан фойдалансанг ҳам бўлади — унда `.env`да `DB_USER=postgres` деб ёзасан.

---

## 6. `.env` файлини яратиш

Лойиҳада `.env.example` намунаси бор. Ундан нусха ол:

```powershell
copy .env.example .env
```

Энди `.env` файлини очиб (масалан, Блокнотда), ичидаги қийматларни тўлдир:

| Ўзгарувчи | Нима ёзасан |
|-----------|-------------|
| `SECRET_KEY` | Узун тасодифий сатр. Яратиш: `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` — чиққан натижани кўчириб қўй |
| `DJANGO_ENV` | `development` (шундай қолдир) |
| `DEBUG` | `True` |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` |
| `DB_NAME` | `skladpro_db` |
| `DB_USER` | `skladpro_user` (ёки `postgres`) |
| `DB_PASSWORD` | 5-қадамда ёзган паролинг |
| `DB_HOST` | `localhost` |
| `DB_PORT` | `5432` |
| `MEDIA_URL` | `/media/` |
| `MEDIA_ROOT` | `media/` |

> ⚠️ Файл номи айнан **`.env`** бўлиши керак (`.env.txt` эмас!) ва `manage.py`
> билан бир папкада турсин.
>
> ⚠️ Эслатма: операцион тизимдаги муҳит ўзгарувчилари `.env`дан устун туради.
> Агар база «нотўғри» уланаётган бўлса, тизимда `DB_NAME` каби ўзгарувчи
> қўйилмаганини текшир: `echo $env:DB_NAME`.

---

## 7. Миграцияларни бажариш (базани тайёрлаш)

```powershell
python manage.py migrate
```

Экранда `Applying ... OK` рўйхати чиқади. Кейин ҳаммаси жойидами — текшир:

```powershell
python manage.py check
```

`System check identified no issues` чиқса — аъло.

---

## 8. Биринчи фойдаланувчи — Супер-администратор

Тизим кўп-компаниялик (SaaS). Энг юқори даража — **супер-администратор**:
у ҳеч бир компанияга тегишли эмас (`company=None`), компанияларни ва уларнинг
эгаларини у яратади.

Супер-админ яратиш:

```powershell
python manage.py createsuperuser
```

Фойдаланувчи номи (username), email (бўш қолдирса ҳам бўлади) ва паролни ёз.
Парол камида 8 та белгидан иборат бўлсин ва жуда оддий бўлмасин. Бу буйруқ
`role=superadmin`, `is_staff=True`, `is_superuser=True`, `company=None` бўлган
фойдаланувчи яратади.

**Кейин нима қиласан — компания ва эгасини яратиш:**
1. `http://localhost:8000/admin/` — Django Admin'га шу супер-админ билан кир.
2. `Companies → Add` — компания номи ва эгасининг маълумотларини (username,
   парол, исм) ёз. Компания ва унинг эгаси бир қадамда яратилади.
3. Компания эгаси сайтга кириб, ўз администратор ва ишчиларини қўшади.

---

## 9. Серверни ишга тушириш

```powershell
python manage.py runserver
```

Тайёр! Одатда манзил — `http://127.0.0.1:8000/`. Энди браузерда шу манзилларни оч:

| Манзил | Нима бу |
|--------|---------|
| http://localhost:8000/ | Сайтнинг ўзи |
| http://localhost:8000/accounts/login/ | Кириш саҳифаси |
| http://localhost:8000/admin/ | Django Admin (супер-админ учун) |
| http://localhost:8000/api/v1/swagger/ | Swagger — интерактив API ҳужжатлари |
| http://localhost:8000/api/v1/redoc/ | ReDoc — API ҳужжатлари |
| http://localhost:8000/api/v1/schema/ | OpenAPI схемаси (YAML) |

Серверни тўхтатиш: терминалда **`Ctrl + C`**.
Бошқа портда ишга тушириш: `python manage.py runserver 8001`.

---

## 10. Тестларни текшириш (ихтиёрий)

Тестлар алоҳида созламадан (SQLite, хотирада) фойдаланади — асл PostgreSQL
базасига тегмайди.

```powershell
# PowerShell
$env:DJANGO_SETTINGS_MODULE="skladpro.test_settings"
python manage.py test
```

```cmd
:: cmd.exe
set DJANGO_SETTINGS_MODULE=skladpro.test_settings
python manage.py test
```

Охирида шундай чиқса — ҳаммаси зўр:

```
Ran 135 tests in ...s

OK
```

---

## 11. Тез-тез учрайдиган хатолар

| Хато | Сабаби / Ечими |
|------|----------------|
| `could not connect to server` / `connection refused` | PostgreSQL хизмати ишламаяпти ёки `.env`даги парол/база нотўғри. Хизматни текшир: `services.msc → postgresql-x64-18`. |
| `password authentication failed` | `.env`даги `DB_USER`/`DB_PASSWORD` нотўғри. Қўлда текшир: `psql -U <DB_USER> -d <DB_NAME> -h localhost`. |
| `permission denied for schema public` | Янги фойдаланувчига схема ҳуқуқи берилмаган. 5-қадамдаги `GRANT ALL ON SCHEMA public...` буйруғини бажар. |
| `ModuleNotFoundError` | venv фаоллашмаган ёки кутубхоналар ўрнатилмаган. `venv\Scripts\Activate.ps1`, кейин `pip install -r requirements.txt`. |
| `That port is already in use` | 8000-порт банд. Бошқа портда ишга тушир: `python manage.py runserver 8001`. |
| `.env` ўқилмаяпти | Файл номи `.env` эканини ва `manage.py` ёнида турганини текшир. |
| Swagger очилмаяпти | Кутубхоналар тўлиқ ўрнатилмаган. `pip install -r requirements.txt`. |
| Сайтда стиллар (CSS) кўринмаяпти | `DEBUG=True` эканини текшир. Прод учун: `python manage.py collectstatic`. |
| Сайтда эски CSS/JS кўриняпти | Браузерда **Ctrl + F5** (кучли янгилаш) бос ёки инкогнито режимда оч. |
| API `401 Unauthorized` | Токен эскирган. `POST /api/v1/accounts/token/refresh/` орқали янгила ёки қайта кир. |

---

## Қисқа хулоса (кетма-кетлик)

```
GitHub Desktop → Clone → Open in PowerShell
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
(PostgreSQL'да база яратиш — 5-қадам)
copy .env.example .env  →  ичини тўлдириш
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
→ браузерда http://localhost:8000/
```

Омад! 🚀
