"""
Messaging services — уведомления и операции корпоративного чата.

Здесь же живёт функция широковещания сообщений чата в WebSocket-группы
(Django Channels). Создание сообщения проходит через REST (валидация,
права, изоляция), а затем broadcast_message() доставляет его онлайн-
участникам мгновенно.
"""
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from .models import ChatMessage, Conversation, ConversationParticipant, Notification, WsTicket


# ─────────────────────────── Уведомления ───────────────────────────

def notify(users, notification_type, title, message, order=None, task=None):
    """Создаёт уведомление каждому пользователю из users (одному или списку)."""
    if not users:
        return []
    if not hasattr(users, '__iter__'):
        users = [users]
    notifications = [
        Notification(
            company_id=user.company_id,
            user=user,
            type=notification_type,
            title=title,
            message=message,
            related_order=order,
            related_task=task,
        )
        for user in users
    ]
    return Notification.objects.bulk_create(notifications)


def notify_staff(company, notification_type, title, message, order=None, task=None):
    """Уведомляет владельца и администраторов указанной компании."""
    from apps.accounts.models import User
    if company is None:
        return []
    company_id = getattr(company, 'id', company)
    staff = User.objects.filter(
        role__in=('owner', 'admin'), is_active=True, company_id=company_id,
    )
    return notify(list(staff), notification_type, title, message, order=order, task=task)


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
        User.objects.select_for_update().filter(pk__in=[user_a.pk, user_b.pk]).order_by('pk').first()
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

    ticket = WsTicket.objects.create(
        company_id=user.company_id,
        user=user,
        ticket=secrets.token_urlsafe(32),
        expires_at=timezone.now() + timedelta(seconds=WS_TICKET_TTL_SECONDS),
    )
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
