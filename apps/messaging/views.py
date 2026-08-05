"""
Views for messaging API — корпоративный чат и уведомления.

ИЗОЛЯЦИЯ (multi-tenant): каждый queryset фильтруется по company текущего
пользователя И по его участию в беседе. Пользователь одной компании не может
получить беседы/сообщения другой даже прямым API-запросом (get_object вернёт
404, т.к. объект вне queryset).
"""
import datetime

from django.db.models import (
    Count, DateTimeField, F, OuterRef, Prefetch, Q, Subquery, Value,
)
from django.db.models.functions import Coalesce
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import User
from apps.core.permissions import IsCompanyMember
from rest_framework.views import APIView

from .models import ChatMessage, Conversation, ConversationParticipant, Notification
from .serializers import (
    ChatMessageCreateSerializer,
    ChatMessageSerializer,
    ConversationSerializer,
    EmployeeSerializer,
    NotificationSerializer,
    StartDirectSerializer,
)
from .services import (
    broadcast_message,
    ensure_general_conversation,
    ensure_participant,
    get_or_create_direct,
    issue_ws_ticket,
    notify,
)

MESSAGE_PAGE = 50  # сколько последних сообщений отдаём при открытии беседы


@extend_schema(tags=['Chat'])
class ConversationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Беседы пользователя: общий чат компании и личные диалоги.
    """
    serializer_class = ConversationSerializer
    permission_classes = [IsCompanyMember]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Conversation.objects.none()
        user = self.request.user
        participants = Prefetch(
            'participants',
            queryset=ConversationParticipant.objects.select_related('user'),
        )
        # Раньше сериализатор на КАЖДУЮ беседу делал отдельные запросы за
        # последним сообщением и счётчиком непрочитанных (N+1). Считаем их
        # подзапросами в одном SQL. Формат ответа не меняется.
        my_last_read = ConversationParticipant.objects.filter(
            conversation=OuterRef('pk'), user=user,
        ).values('last_read_at')[:1]
        last_msg = ChatMessage.objects.filter(
            conversation=OuterRef('pk'),
        ).order_by('-created_at')
        # Если участник ещё не читал беседу — считаем непрочитанным всё, поэтому
        # подставляем «нулевую» дату вместо NULL.
        epoch = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
        return (
            Conversation.objects.filter(company_id=user.company_id)
            .filter(Q(participants__user=user) | Q(kind=Conversation.Kind.GENERAL))
            .prefetch_related(participants)
            .annotate(
                my_last_read=Coalesce(
                    Subquery(my_last_read), Value(epoch, output_field=DateTimeField()),
                ),
                last_msg_content=Subquery(last_msg.values('content')[:1]),
                last_msg_created=Subquery(last_msg.values('created_at')[:1]),
                last_msg_sender=Subquery(last_msg.values('sender_id')[:1]),
                last_msg_sender_name=Subquery(last_msg.values('sender__full_name')[:1]),
                last_msg_sender_username=Subquery(last_msg.values('sender__username')[:1]),
            )
            .annotate(
                unread_total=Count(
                    'messages',
                    filter=~Q(messages__sender=user) & Q(messages__created_at__gt=F('my_last_read')),
                    distinct=True,
                ),
            )
            .distinct()
        )

    def list(self, request, *args, **kwargs):
        # Гарантируем существование общего чата и членства пользователя в нём.
        general = ensure_general_conversation(request.user.company)
        ensure_participant(general, request.user)
        return super().list(request, *args, **kwargs)

    @extend_schema(responses=ConversationSerializer)
    @action(detail=False, methods=['get'])
    def general(self, request):
        """Общий чат компании (создаётся при первом обращении)."""
        general = ensure_general_conversation(request.user.company)
        ensure_participant(general, request.user)
        return Response(self.get_serializer(general).data)

    @extend_schema(request=StartDirectSerializer, responses=ConversationSerializer)
    @action(detail=False, methods=['post'])
    def start_direct(self, request):
        """Открыть (или создать) личный диалог с сотрудником своей компании."""
        serializer = StartDirectSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        other = serializer.context['other_user']
        conversation, _ = get_or_create_direct(request.user.company, request.user, other)
        ensure_participant(conversation, request.user)
        return Response(
            self.get_serializer(conversation).data, status=status.HTTP_200_OK,
        )

    @extend_schema(responses=ChatMessageSerializer(many=True))
    @action(detail=True, methods=['get'])
    def messages(self, request, pk=None):
        """Последние сообщения беседы (в хронологическом порядке)."""
        conversation = self.get_object()
        qs = (
            ChatMessage.objects.filter(conversation=conversation)
            .select_related('sender')
            .order_by('-created_at')[:MESSAGE_PAGE]
        )
        messages = list(reversed(qs))
        data = ChatMessageSerializer(messages, many=True, context={'request': request}).data
        return Response(data)

    @extend_schema(request=None, responses={200: None})
    @action(detail=True, methods=['post'])
    def read(self, request, pk=None):
        """Отметить беседу прочитанной (сдвинуть указатель last_read_at)."""
        conversation = self.get_object()
        participant = ensure_participant(conversation, request.user)
        participant.last_read_at = timezone.now()
        participant.save(update_fields=['last_read_at', 'updated_at'])
        return Response({'detail': 'ok'})


@extend_schema(tags=['Chat'])
class ChatMessageViewSet(viewsets.GenericViewSet):
    """
    Отправка сообщений в чат.

    POST /api/v1/messaging/messages/  {conversation, content}
    """
    permission_classes = [IsCompanyMember]
    serializer_class = ChatMessageCreateSerializer
    queryset = ChatMessage.objects.none()  # для интроспекции схемы

    @extend_schema(request=ChatMessageCreateSerializer, responses=ChatMessageSerializer)
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        conversation = serializer.validated_data['conversation']

        message = ChatMessage.objects.create(
            company_id=conversation.company_id,
            conversation=conversation,
            sender=request.user,
            content=serializer.validated_data['content'],
        )

        # Беседа поднимается наверх списка; авто-поля обходим явным update.
        now = timezone.now()
        Conversation.objects.filter(pk=conversation.pk).update(updated_at=now)

        # Отправитель уже «прочитал» своё сообщение.
        participant = ensure_participant(conversation, request.user)
        participant.last_read_at = now
        participant.save(update_fields=['last_read_at', 'updated_at'])

        broadcast_message(message)

        # Уведомление о личном сообщении: получатель может быть не на вкладке
        # чата (замечание тестировщика — про новые сообщения узнавали только
        # из WebSocket, пока страница открыта). Для общего чата уведомление
        # не создаём — каждый писать не может, а непрочитанные счётчики и так
        # висят на вкладке чата.
        if conversation.kind == Conversation.Kind.DIRECT:
            recipients = (
                ConversationParticipant.objects
                .filter(conversation=conversation)
                .exclude(user=request.user)
                .select_related('user')
            )
            for participant in recipients:
                # Уведомление создаём только за ПЕРВОЕ непрочитанное сообщение
                # беседы. Если у получателя уже есть непрочитанные — он их видит
                # по счётчику вкладки чата, и каждое следующее сообщение плодило
                # бы спам из уведомлений (замечание тестировщика).
                previous_unread = ChatMessage.objects.filter(
                    conversation=conversation,
                ).exclude(sender=participant.user).exclude(pk=message.pk)
                if participant.last_read_at:
                    previous_unread = previous_unread.filter(created_at__gt=participant.last_read_at)
                if previous_unread.exists():
                    continue
                notify(
                    participant.user,
                    Notification.NotificationType.NEW_MESSAGE,
                    request.user.full_name or request.user.username,
                    message.content[:200],
                )

        out = ChatMessageSerializer(message, context={'request': request})
        return Response(out.data, status=status.HTTP_201_CREATED)


@extend_schema(tags=['Chat'])
class WsTicketView(APIView):
    """
    GET /api/v1/messaging/ws-ticket/ — одноразовый тикет для WebSocket чата.

    Тикет короткоживущий (60 сек), не заменяет собой access-токен: его хватает
    только на одно соединение. Токен в query-строке WebSocket-URL не передаётся
    именно потому, что он оседал бы в логах прокси/балансировщиков.
    """
    permission_classes = [IsCompanyMember]

    def get(self, request):
        if request.user.is_superadmin or request.user.company_id is None:
            return Response({'error': 'Чат доступен только сотрудникам компании.'}, status=status.HTTP_403_FORBIDDEN)
        return Response({'ticket': issue_ws_ticket(request.user)})


@extend_schema(tags=['Chat'])
class EmployeeViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Сотрудники компании — контакты для чата. Поиск: ?search=<имя|логин>.
    """
    serializer_class = EmployeeSerializer
    permission_classes = [IsCompanyMember]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return User.objects.none()
        user = self.request.user
        qs = User.objects.filter(
            company_id=user.company_id, is_active=True,
        ).exclude(pk=user.pk).exclude(role=User.Role.SUPERADMIN)

        # Флаг can_see_other_workers (у admin и worker, owner видит всегда):
        # без него в контактах видны только admin/owner/manager — работники
        # скрыты, и личный диалог с ними не начнётся (зеркально валидатору).
        if not user.is_owner and not user.can_see_other_workers:
            qs = qs.exclude(role=User.Role.WORKER)

        search = self.request.query_params.get('search')
        if search:
            # Транслит: «Gulnora» находит «Гулнора» и наоборот (apps/core/translit.py).
            from apps.core.translit import translit_search_qs
            qs = translit_search_qs(qs, search, ['full_name', 'username'])
        return qs.order_by('full_name', 'username')


@extend_schema(tags=['Notifications'])
class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet для просмотра уведомлений.

    Только чтение, уведомления создаются автоматически системой.
    """
    queryset = Notification.objects.all()  # для интроспекции схемы; runtime-фильтрация ниже
    permission_classes = [IsCompanyMember]
    serializer_class = NotificationSerializer

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Notification.objects.none()
        user = self.request.user
        queryset = Notification.objects.filter(
            user=user, company_id=user.company_id,
        ).select_related('user', 'related_order', 'related_task')

        is_read = self.request.query_params.get('is_read')
        if is_read is not None:
            queryset = queryset.filter(is_read=is_read.lower() == 'true')

        return queryset

    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):
        """Помечает уведомление как прочитанное."""
        notification = self.get_object()
        if notification.user != request.user:
            return Response(
                {'detail': 'You can only mark your own notifications as read'},
                status=status.HTTP_403_FORBIDDEN,
            )
        notification.is_read = True
        notification.read_at = timezone.now()
        notification.save()
        return Response(self.get_serializer(notification).data)

    @action(detail=False, methods=['post'])
    def mark_all_read(self, request):
        """Помечает все уведомления как прочитанные."""
        request.user.notifications.filter(is_read=False).update(
            is_read=True, read_at=timezone.now(),
        )
        return Response({'detail': 'All notifications marked as read'})
