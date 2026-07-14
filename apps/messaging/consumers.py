"""
WebSocket-консьюмер корпоративного чата (Django Channels).

Каждое соединение подписывается на персональную группу пользователя
`chat_user_<id>`. Отправка сообщений идёт через REST (там валидация, права
и изоляция), а сервис broadcast_message() доставляет их в эти группы —
консьюмер лишь пересылает событие клиенту.
"""
from channels.generic.websocket import AsyncJsonWebsocketConsumer


class ChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get('user')
        # Только аутентифицированные сотрудники компании (не супер-админ).
        if not user or not user.is_authenticated or user.is_superadmin or user.company_id is None:
            await self.close(code=4401)
            return
        self.user = user
        self.group_name = f'chat_user_{user.id}'
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send_json({'type': 'connected'})

    async def disconnect(self, code):
        group = getattr(self, 'group_name', None)
        if group is not None:
            await self.channel_layer.group_discard(group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        # MVP: входящие полезной нагрузки не требуют обработки. Отвечаем на ping,
        # чтобы клиент мог держать соединение живым.
        if content.get('type') == 'ping':
            await self.send_json({'type': 'pong'})

    async def chat_message(self, event):
        """Обработчик события 'chat.message' из group_send — шлём клиенту."""
        await self.send_json({'type': 'message', 'message': event['message']})
