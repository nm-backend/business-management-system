"""
Messaging services — уведомления и операции корпоративного чата.

Здесь же живёт функция широковещания сообщений чата в WebSocket-группы
(Django Channels). Создание сообщения проходит через REST (валидация,
права, изоляция), а затем broadcast_message() доставляет его онлайн-
участникам мгновенно.
"""
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from core.utils import translate

from .models import ChatMessage, Conversation, ConversationParticipant, Notification, WsTicket


# ─────────────────────────── Уведомления ───────────────────────────

def notify(users, notification_type, title=None, message=None, order=None, task=None,
           company=None, *, title_key=None, message_key=None, params=None):
    """
    Создаёт уведомление каждому пользователю из users (одному или списку).

    Локализация (требование ТЗ «уведомления переводятся на оба языка»):
    вместо готовой строки передаётся ключ локали + параметры
    (title_key/message_key/params). Тогда каждому получателю в title/message
    кладётся снимок текста НА ЕГО языке (его читает Web Push, который уходит
    сразу), а сериализатор потом рендерит текст заново по текущему языку
    пользователя. Явные title/message тоже поддерживаются — там, где текст
    непереводим по своей природе (имя отправителя, название компании,
    комментарий работника).

    company: явная привязка к компании-источнику. По умолчанию — компания
    пользователя; нужна платформенным уведомлениям супер-админа (у него
    своей компании нет, а уведомление должно ссылаться на компанию, о
    которой речь).
    """
    if not users:
        return []
    if not hasattr(users, '__iter__'):
        users = [users]
    params = params or {}
    notifications = []
    for user in users:
        lang = getattr(user, 'language', None) or 'uz_cyrl'
        notifications.append(Notification(
            company_id=(company.id if company is not None else user.company_id),
            user=user,
            type=notification_type,
            title=(translate(title_key, lang, params) if title_key else (title or '')),
            message=(translate(message_key, lang, params) if message_key else (message or '')),
            title_key=title_key or '',
            message_key=message_key or '',
            params=params,
            related_order=order,
            related_task=task,
        ))
    return Notification.objects.bulk_create(notifications)


def notify_staff(company, notification_type, title=None, message=None, order=None, task=None,
                 *, title_key=None, message_key=None, params=None):
    """Уведомляет владельца и администраторов указанной компании."""
    from apps.accounts.models import User
    if company is None:
        return []
    company_id = getattr(company, 'id', company)
    staff = User.objects.filter(
        role__in=('owner', 'admin'), is_active=True, company_id=company_id,
    )
    return notify(
        list(staff), notification_type, title, message, order=order, task=task,
        title_key=title_key, message_key=message_key, params=params,
    )


# ─────────────────────────── Чат ───────────────────────────

GENERAL_TITLE = 'General'


def ensure_general_conversation(company):
    """Возвращает (создавая при необходимости) общий чат компании."""
    conversation, _ = Conversation.objects.get_or_create(
        company_id=getattr(company, 'id', company),
        kind=Conversation.Kind.GENERAL,
        defaults={'title': GENERAL_TITLE},
    )
    return conversation


def ensure_participant(conversation, user):
    """
    Гарантирует членство пользователя в беседе.

    При первом входе last_read_at ставится в «сейчас», чтобы уже существующая
    история не считалась целиком непрочитанной.
    """
    participant, _ = ConversationParticipant.objects.get_or_create(
        conversation=conversation,
        user=user,
        defaults={'last_read_at': timezone.now()},
    )
    return participant


def get_or_create_direct(company, user_a, user_b):
    """
    Возвращает личный диалог двух пользователей одной компании, создавая
    его при необходимости. Оба участника должны принадлежать company.
    """
    company_id = getattr(company, 'id', company)
    # Диалог, где ровно эти два участника. Ищем через промежуточную модель,
    # не смешивая filter и annotate по одной и той же связи (иначе Count даёт
    # неверную кратность из-за повторных JOIN).
    convs_with_a = ConversationParticipant.objects.filter(
        user=user_a,
        conversation__company_id=company_id,
        conversation__kind=Conversation.Kind.DIRECT,
    ).values_list('conversation_id', flat=True)
    shared_ids = ConversationParticipant.objects.filter(
        user=user_b, conversation_id__in=convs_with_a,
    ).values_list('conversation_id', flat=True)
    existing = (
        Conversation.objects.filter(id__in=shared_ids)
        .annotate(n=Count('participants'))
        .filter(n=2)
        .first()
    )
    if existing:
        return existing, False

    # Два параллельных запроса оба могли не найти диалог и создать два.
    # Блокируем строки обоих пользователей: создание пары сериализуется,
    # второй поток после блокировки увидит диалог, созданный первым.
    from apps.accounts.models import User
    with transaction.atomic():
        list(User.objects.select_for_update().filter(pk__in=[user_a.pk, user_b.pk]).order_by('pk'))
        convs_with_a = ConversationParticipant.objects.filter(
            user=user_a,
            conversation__company_id=company_id,
            conversation__kind=Conversation.Kind.DIRECT,
        ).values_list('conversation_id', flat=True)
        shared_ids = ConversationParticipant.objects.filter(
            user=user_b, conversation_id__in=convs_with_a,
        ).values_list('conversation_id', flat=True)
        existing = (
            Conversation.objects.filter(id__in=shared_ids)
            .annotate(n=Count('participants'))
            .filter(n=2)
            .first()
        )
        if existing:
            return existing, False

        conversation = Conversation.objects.create(
            company_id=company_id,
            kind=Conversation.Kind.DIRECT,
            created_by=user_a,
        )
        ConversationParticipant.objects.bulk_create([
            ConversationParticipant(conversation=conversation, user=user_a, last_read_at=timezone.now()),
            ConversationParticipant(conversation=conversation, user=user_b),
        ])
    return conversation, True


# ─────────────────────────── WS-тикеты ───────────────────────────

WS_TICKET_TTL_SECONDS = 60


def issue_ws_ticket(user):
    """
    Выдаёт одноразовый тикет для WebSocket-соединения чата.

    Тикет короткоживущий (60 секунд) и привязан к пользователю. Он заменяет
    передачу access-токена в query-строке WebSocket-URL (токен оседал бы
    в логах прокси и балансировщиков).
    """
    import secrets

    from datetime import timedelta

    now = timezone.now()
    # Чистка при каждой выдаче: использованные, истёкшие и старые тикеты
    # удаляются. Раньше GET /ws-ticket/ плодил строку на КАЖДЫЙ вызов, а
    # WsTicket нигде не чистился — таблица росла бесконечно (страница чата
    # запрашивает тикет при каждом открытии вкладки).
    WsTicket.objects.filter(user=user).filter(
        Q(used=True) | Q(expires_at__lt=now) | Q(created_at__lt=now - timedelta(hours=1)),
    ).delete()

    ticket = WsTicket.objects.create(
        company_id=user.company_id,
        user=user,
        ticket=secrets.token_urlsafe(32),
        expires_at=now + timedelta(seconds=WS_TICKET_TTL_SECONDS),
    )

    # Лимит одновременно активных тикетов на пользователя: клиент мог
    # накопить десятки неиспользованных (каждое открытие чата — новый тикет,
    # старый протухает через 60 секунд, но до этого момента «активен»).
    # Оставляем не больше 5 свежих — остальные отзываем.
    active = list(
        WsTicket.objects.filter(user=user, used=False, expires_at__gt=now)
        .order_by('-created_at')
        .values_list('id', flat=True)
    )
    if len(active) > 5:
        WsTicket.objects.filter(id__in=active[5:]).delete()

    return ticket.ticket


def unread_count(conversation, user):
    """Число непрочитанных сообщений беседы для пользователя."""
    participant = conversation.participants.filter(user=user).first()
    qs = ChatMessage.objects.filter(conversation=conversation).exclude(sender=user)
    if participant and participant.last_read_at:
        qs = qs.filter(created_at__gt=participant.last_read_at)
    return qs.count()


def recipient_user_ids(conversation):
    """
    ID пользователей, которым нужно доставить сообщение беседы в реальном времени.

    DIRECT/GROUP — участники беседы. GENERAL — все активные сотрудники компании
    (общий чат виден всем в компании).
    """
    from apps.accounts.models import User
    if conversation.kind == Conversation.Kind.GENERAL:
        return list(
            User.objects.filter(company_id=conversation.company_id, is_active=True)
            .values_list('id', flat=True)
        )
    return list(conversation.participants.values_list('user_id', flat=True))


def broadcast_message(message):
    """
    Рассылает новое сообщение чата онлайн-получателям через Channels.

    Никогда не роняет запрос: если канальный слой недоступен, просто выходим —
    сообщение уже сохранено и придёт при следующей загрузке.
    """
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
    except Exception:  # channels не установлен — тихо выходим
        return

    try:
        channel_layer = get_channel_layer()
        if channel_layer is None:
            return

        payload = {
            'type': 'chat.message',  # -> ChatConsumer.chat_message
            'message': {
                'id': message.id,
                'conversation': message.conversation_id,
                'conversation_kind': message.conversation.kind,
                'company': message.company_id,
                'sender': message.sender_id,
                'sender_name': message.sender.full_name or message.sender.username,
                'content': message.content,
                'attachment': message.attachment.url if message.attachment else None,
                'attachment_name': message.attachment_name,
                'created_at': message.created_at.isoformat(),
            },
        }
        for uid in recipient_user_ids(message.conversation):
            async_to_sync(channel_layer.group_send)(f'chat_user_{uid}', payload)
    except Exception:
        # Канальный слой (Redis) недоступен/упал — сообщение уже сохранено,
        # доедет при следующей загрузке. Не роняем запрос: клиент иначе
        # получил бы 500 и отправил бы сообщение повторно (дубликат).
        return
