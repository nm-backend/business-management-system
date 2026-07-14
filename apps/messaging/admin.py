"""Messaging admin — чат (беседы, участники, сообщения) и уведомления."""
from django.contrib import admin

from .models import ChatMessage, Conversation, ConversationParticipant, Notification


class ConversationParticipantInline(admin.TabularInline):
    model = ConversationParticipant
    extra = 0
    autocomplete_fields = ('user',)
    readonly_fields = ('last_read_at', 'created_at')


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('id', 'company', 'kind', 'title', 'created_by', 'updated_at')
    list_filter = ('company', 'kind', 'created_at')
    search_fields = ('title', 'created_by__username', 'participants__user__username')
    autocomplete_fields = ('company', 'created_by')
    date_hierarchy = 'created_at'
    ordering = ('-updated_at',)
    readonly_fields = ('created_at', 'updated_at')
    inlines = (ConversationParticipantInline,)


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'company', 'conversation', 'sender', 'short_content', 'created_at')
    list_filter = ('company', 'created_at')
    search_fields = ('content', 'sender__username', 'sender__full_name')
    autocomplete_fields = ('company', 'conversation', 'sender')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')

    @admin.display(description='Content')
    def short_content(self, obj):
        return (obj.content[:60] + '…') if len(obj.content) > 60 else obj.content


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('id', 'company', 'user', 'type', 'title', 'is_read', 'created_at')
    list_filter = ('company', 'type', 'is_read', 'created_at')
    search_fields = ('title', 'message', 'user__username')
    autocomplete_fields = ('company', 'user', 'related_order', 'related_task')
    date_hierarchy = 'created_at'
    readonly_fields = ('read_at', 'created_at', 'updated_at')
    ordering = ('-created_at',)
