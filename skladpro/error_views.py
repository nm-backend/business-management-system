from django.http import HttpResponse

# ⚠️ Inline HTML error pages.
# Django 5.1 + Python 3.14 have a bug in Context.__copy__
# (AttributeError: 'super' object has no attribute 'dicts')
# that crashes ANY template render during testing.
# These lightweight pages dodge the Django template engine entirely.

_ERROR_403 = '''<!DOCTYPE html><html lang="uz"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>403 — Taqiqlangan</title>
<style>body{font-family:sans-serif;text-align:center;padding:80px 20px}
h1{font-size:72px;color:#e53e3e;margin:0}p{font-size:18px;color:#4a5568}
</style></head><body><h1>403</h1>
<p>Bu sahifaga kirish taqiqlangan — Sizda ruxsat yo‘q.</p>
<hr><p>Access denied — у вас нет прав для просмотра этой страницы.</p>
</body></html>'''

_ERROR_404 = '''<!DOCTYPE html><html lang="uz"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>404 — Topilmadi</title>
<style>body{font-family:sans-serif;text-align:center;padding:80px 20px}
h1{font-size:72px;color:#ecc94b;margin:0}p{font-size:18px;color:#4a5568}
</style></head><body><h1>404</h1>
<p>Sahifa topilmadi — страница не найдена.</p>
</body></html>'''

_ERROR_500 = '''<!DOCTYPE html><html lang="uz"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>500 — Server xatosi</title>
<style>body{font-family:sans-serif;text-align:center;padding:80px 20px}
h1{font-size:72px;color:#e53e3e;margin:0}p{font-size:18px;color:#4a5568}
</style></head><body><h1>500</h1>
<p>Serverda xatolik yuz berdi — внутренняя ошибка сервера.</p>
<p>Iltimos keyinroq urinib ko‘ring — пожалуйста, попробуйте позже.</p>
</body></html>'''


def error_403(request, exception=None):
    return HttpResponse(_ERROR_403, status=403)


def error_404(request, exception=None):
    return HttpResponse(_ERROR_404, status=404)


def error_500(request):
    return HttpResponse(_ERROR_500, status=500)
