"""
Защищённая отдача медиафайлов (/media/).

Раньше /media/ раздавался через django.views.static.serve БЕЗ авторизации:
любой, узнавший URL, скачивал чеки, аватары и аттачменты чужой компании
(имена файлов частично предсказуемы: 'avatars/', 'chat/attachments/%Y/%m/').
Теперь каждый запрос проходит:
  1. аутентификацию — сессия Django (админка) ИЛИ JWT access-токен SPA;
  2. проверку подписки компании (замороженная — 403, как в API-gate);
  3. поиск владельца файла в БД по префиксу пути (файл без владельца —
     404, даже если он физически лежит на диске);
  4. ролевую проверку, зеркалящую права соответствующего API-эндпоинта.

Как отдаются байты (решение принимает Django ПОСЛЕ проверки прав):
  - dev / PaaS без reverse-proxy: FileResponse из процесса Django;
  - nginx: пустой ответ с X-Accel-Redirect на internal-location
    (настройка PROTECTED_MEDIA_ACCEL_LOCATION, например '/protected-media/');
  - Apache (mod_xsendfile): X-Sendfile (PROTECTED_MEDIA_SENDFILE=True).

ВАЖНО для reverse-proxy: /media/ НЕЛЬЗЯ отдавать с nginx напрямую
(alias/root без проксирования) — это вернёт дыру. Правильно:
  location /media/               { proxy_pass http://django; }  # проверки здесь
  location /protected-media/     { internal; alias /app/media/; }  # только байты

S3-режим (production с AWS_STORAGE_BUCKET_NAME): MEDIA_URL тогда абсолютный,
маршрут ниже не монтируется, а браузер ходит в бакет напрямую. Текущая
конфигурация бакета — public-read (см. production.py): это известный
остаточный риск, полное закрытие требует private ACL + подписываемые URL.
"""
import mimetypes
import posixpath
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect

from apps.accounts.authentication import ActivityJWTAuthentication
from apps.companies.models import Company
from apps.finance.models import Expense
from apps.messaging.models import (
    ChatMessage,
    Conversation,
    ConversationParticipant,
)
from apps.orders.models import Order
from apps.production.models import Task, WorkPhoto, WorkRecord
from apps.warehouse.models import FinishedProduct, RawMaterial

#: Код ответа, когда компания заморожена — тот же, что у API-gate
#: (apps/billing/gate.py), чтобы фронтенд показывал экран «Подписка истекла».
SUBSCRIPTION_EXPIRED_CODE = 'subscription_expired'


# ── Аутентификация ────────────────────────────────────────────────

def _resolve_user(request):
    """Пользователь по сессии ИЛИ по JWT. None — аноним (401)."""
    user = getattr(request, 'user', None)
    if user is not None and user.is_authenticated and user.is_active:
        return user
    try:
        result = ActivityJWTAuthentication().authenticate(request)
    except Exception:
        return None
    if result is None:
        return None
    user, _token = result
    if user is None or not getattr(user, 'is_active', False):
        return None
    return user


# ── Безопасный путь ───────────────────────────────────────────────

def _clean_relative_path(raw_path):
    """Нормализует путь внутри MEDIA_ROOT. Траверс/мусор — 404, не 500."""
    if not raw_path or '\x00' in raw_path or '\\' in raw_path:
        raise Http404
    normalized = posixpath.normpath(raw_path)
    if (
        normalized in ('.', '..')
        or normalized.startswith('../')
        or normalized.startswith('/')
    ):
        raise Http404
    media_root = Path(settings.MEDIA_ROOT).resolve()
    full = (media_root / normalized).resolve()
    # resolve() без strict не падает на несуществующих путях, но раскрывает
    # '..' и симлинки: файл обязан остаться внутри MEDIA_ROOT.
    if full != media_root and media_root not in full.parents:
        raise Http404
    return normalized


# ── Ролевые проверки (зеркало прав API) ──────────────────────────

def _same_company(user, company_id):
    return (
        user.company_id is not None
        and company_id is not None
        and user.company_id == company_id
    )


def _can_view_avatar(user, owner):
    # Своё фото — всегда (покрывает и суперадмина с company=None).
    if owner.pk == user.pk:
        return True
    # Суперадмин управляет аккаунтами через Django Admin (там же видит фото):
    # аватары — учётные данные, а не бизнес-контент, доступ разрешён.
    if user.is_superadmin:
        return True
    # URL аватаров и так отдаются участникам чата (sender.avatar), поэтому
    # внутри своей компании фото видит любой сотрудник.
    return _same_company(user, owner.company_id)


def _can_view_logo(user, company):
    if user.is_superadmin:
        return True
    return _same_company(user, company.pk)


def _can_view_receipt(user, expense):
    # Чеки — финансовые данные: только владелец (как FinancialDataPermission).
    return user.is_owner and _same_company(user, expense.company_id)


def _can_view_chat_attachment(user, message):
    if not _same_company(user, message.company_id):
        return False
    # Зеркало ConversationViewSet.get_queryset: общий чат читают все
    # сотрудники, личный диалог — только его участники.
    kind = (
        Conversation.objects.filter(pk=message.conversation_id)
        .values_list('kind', flat=True)
        .first()
    )
    if kind == Conversation.Kind.GENERAL:
        return True
    return ConversationParticipant.objects.filter(
        conversation_id=message.conversation_id, user_id=user.pk,
    ).exists()


def _can_view_order_photo(user, order):
    # Зеркало OrderViewSet.get_queryset: работник видит только свои заказы.
    if not _same_company(user, order.company_id):
        return False
    if user.is_worker and order.worker_id != user.pk:
        return False
    return True


def _can_view_task_attachment(user, task):
    # Зеркало TaskViewSet.get_queryset: работник видит только свои задачи.
    if not _same_company(user, task.company_id):
        return False
    if user.is_worker and task.worker_id != user.pk:
        return False
    return True


def _can_view_work_photo(user, work):
    # Зеркало WorkRecordViewSet.get_queryset: работник видит свои работы.
    if not _same_company(user, work.company_id):
        return False
    if user.is_worker and work.worker_id != user.pk:
        return False
    return True


def _can_view_work_photo_image(user, photo):
    return _can_view_work_photo(user, photo.work)


def _can_view_stock_photo(user, obj):
    # Фото склада видят все сотрудники компании (как и количества в API).
    return _same_company(user, obj.company_id)


# (префикс upload_to, модель, поле файла, проверка, select_related)
_RESOLVERS = (
    ('avatars/', lambda: get_user_model(), 'avatar', _can_view_avatar, ()),
    ('company_logos/', lambda: Company, 'logo', _can_view_logo, ()),
    ('finance/receipts/', lambda: Expense, 'receipt_photo',
     _can_view_receipt, ()),
    ('chat/attachments/', lambda: ChatMessage, 'attachment',
     _can_view_chat_attachment, ()),
    ('orders/', lambda: Order, 'photo', _can_view_order_photo, ()),
    ('tasks/attachments/', lambda: Task, 'attachment',
     _can_view_task_attachment, ()),
    ('production/work_photos/', lambda: WorkRecord, 'photo',
     _can_view_work_photo, ()),
    ('production/work_photos/', lambda: WorkPhoto, 'image',
     _can_view_work_photo_image, ('work',)),
    ('materials/', lambda: RawMaterial, 'photo', _can_view_stock_photo, ()),
    ('products/', lambda: FinishedProduct, 'photo',
     _can_view_stock_photo, ()),
)


def _find_owner(relative_path):
    """Ищет (объект, проверка) по префиксу пути. Нет владельца — 404."""
    for prefix, model_getter, field, checker, select_related in _RESOLVERS:
        if not relative_path.startswith(prefix):
            continue
        queryset = model_getter().objects.filter(**{field: relative_path})
        if select_related:
            queryset = queryset.select_related(*select_related)
        obj = queryset.first()
        if obj is not None:
            return obj, checker
    raise Http404


# ── Отдача байтов ────────────────────────────────────────────────

def _serve_authorized_file(relative_path):
    """Отдаёт файл авторизованному пользователю (проверки уже пройдены)."""
    content_type = (
        mimetypes.guess_type(relative_path)[0] or 'application/octet-stream'
    )
    accel_location = getattr(settings, 'PROTECTED_MEDIA_ACCEL_LOCATION', '')
    if accel_location:
        # nginx отдаёт байты сам: Django вернул только заголовок.
        response = HttpResponse()
        response['X-Accel-Redirect'] = (
            f'{accel_location.rstrip("/")}/{relative_path}'
        )
        response['Content-Type'] = content_type
        return response
    if getattr(settings, 'PROTECTED_MEDIA_SENDFILE', False):
        full = Path(settings.MEDIA_ROOT) / relative_path
        if not full.is_file():
            raise Http404
        response = HttpResponse()
        response['X-Sendfile'] = str(full.resolve())
        response['Content-Type'] = content_type
        return response
    if not hasattr(default_storage, 'path'):
        # Удалённое хранилище (S3): локального файла нет. Пользователь уже
        # авторизован, поэтому отдаём URL хранилища редиректом.
        if not default_storage.exists(relative_path):
            raise Http404
        return redirect(default_storage.url(relative_path))
    full = Path(default_storage.path(relative_path))
    if not full.is_file():
        raise Http404
    return FileResponse(
        full.open('rb'), content_type=content_type,
    )


# ── View ──────────────────────────────────────────────────────────

def serve_protected_media(request, path):
    """GET /media/<path> — файл своей компании после проверки прав."""
    if request.method not in ('GET', 'HEAD'):
        return JsonResponse(
            {'detail': 'Метод не поддерживается.', 'code': 'method_not_allowed'},
            status=405,
        )
    user = _resolve_user(request)
    if user is None:
        return JsonResponse(
            {'detail': 'Требуется аутентификация.',
             'code': 'authentication_required'},
            status=401,
        )
    if user.company_id is not None:
        # Замороженная компания не читает даже свои файлы — как в API-gate.
        # user.company подтянут select_related в JWT-слое; для сессии — 1 запрос.
        if not user.company.is_subscription_active:
            return JsonResponse(
                {'detail': (
                    'Подписка компании истекла. Продлите подписку, '
                    'чтобы продолжить работу.'
                ),
                 'code': SUBSCRIPTION_EXPIRED_CODE},
                status=403,
            )
    relative_path = _clean_relative_path(path or '')
    obj, checker = _find_owner(relative_path)
    if not checker(user, obj):
        return JsonResponse(
            {'detail': 'Нет доступа к этому файлу.', 'code': 'forbidden'},
            status=403,
        )
    return _serve_authorized_file(relative_path)
