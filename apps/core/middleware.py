"""
Заголовки безопасности: Content-Security-Policy и Permissions-Policy.

Django через SecurityMiddleware уже ставит X-Frame-Options, X-Content-Type-Options
и Referrer-Policy (проверено curl'ом), но CSP и Permissions-Policy не ставит.
Здесь добавляем именно их, без сторонних зависимостей.

ОБОСНОВАНИЕ ИСКЛЮЧЕНИЙ (CSP_EXEMPT_PREFIXES):
- /api/v1/swagger/, /api/v1/redoc/ — drf-spectacular грузит UI с ВНЕШНЕГО CDN
  (SWAGGER_UI_DIST не задан) и использует inline-стили; строгая CSP их ломает.
- /admin/ — Django Admin содержит собственные inline-скрипты; ломать рабочий
  инструмент администратора недопустимо.
Основная поверхность XSS — пользовательское SPA и страницы входа, они защищены.

ПОЧЕМУ style-src допускает 'unsafe-inline':
приложение и админка широко используют атрибуты style="...", а nonce на inline-
атрибуты по спецификации не распространяется. Скрипты при этом защищены nonce —
это и есть основной барьер против XSS.
"""
import secrets

CSP_EXEMPT_PREFIXES = ('/admin/', '/api/v1/swagger/', '/api/v1/redoc/')

PERMISSIONS_POLICY = (
    'geolocation=(), microphone=(), camera=(), payment=(), usb=(), magnetometer=()'
)


class SecurityHeadersMiddleware:
    """Добавляет CSP (с nonce) и Permissions-Policy к HTML-ответам."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # nonce должен существовать ДО рендера шаблона.
        nonce = secrets.token_urlsafe(16)
        request.csp_nonce = nonce

        response = self.get_response(request)

        # Permissions-Policy безопасен для любых ответов.
        response.headers.setdefault('Permissions-Policy', PERMISSIONS_POLICY)

        # NOTE: Service-Worker-Allowed больше не ставится через middleware.
        # SW обслуживается по URL /sw.js через отдельный URL-паттерн (root scope).

        if request.path.startswith(CSP_EXEMPT_PREFIXES):
            return response

        content_type = response.headers.get('Content-Type', '')
        if 'text/html' not in content_type:
            return response

        response.headers.setdefault('Content-Security-Policy', '; '.join([
            "default-src 'self'",
            "base-uri 'self'",
            "frame-ancestors 'none'",
            "object-src 'none'",
            "img-src 'self' data: blob:",
            "font-src 'self' https://fonts.gstatic.com data:",
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
            f"script-src 'self' 'nonce-{nonce}'",
            "connect-src 'self' ws: wss:",   # WebSocket-чат
            "form-action 'self'",
        ]))
        return response
