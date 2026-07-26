# Run doc — SkladPro preview server

## Background

`skladpro/settings/preview.py` provides a zero-config Django settings module
for live preview. It uses a file-based SQLite database and inherits all
development features (debug toolbar, browsable DRF API, django-extensions).

No `.env` file is required — `preview.py` sets default environment variables
before importing the base settings.

## How to run the server

```bash
# 1. Apply migrations
python manage.py migrate --settings=skladpro.settings.preview

# 2. (Optional) Load demo data
python manage.py load_demo_data --settings=skladpro.settings.preview

# 3. Start dev server
python manage.py runserver 0.0.0.0:8000 --settings=skladpro.settings.preview
```

The server starts on `http://0.0.0.0:8000/`. The first page is the setup
wizard (`/accounts/setup/`). After creating the owner account, you can log
in at `/accounts/login/`.
