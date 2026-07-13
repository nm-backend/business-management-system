"""Messaging admin."""
from django.contrib import admin

from .models import Message, Notification


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'company', 'sender', 'recipient', 'is_group', 'is_read', 'created_at')
    list_filter = ('company', 'is_group', 'is_read', 'created_at')
    search_fields = ('subject', 'content', 'sender__username', 'recipient__username')
    autocomplete_fields = ('company', 'sender', 'recipient')
    date_hierarchy = 'created_at'
    readonly_fields = ('read_at', 'created_at', 'updated_at')
    ordering = ('-created_at',)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('id', 'company', 'user', 'type', 'title', 'is_read', 'created_at')
    list_filter = ('company', 'type', 'is_read', 'created_at')
    search_fields = ('title', 'message', 'user__username')
    autocomplete_fields = ('company', 'user', 'related_order', 'related_task')
    date_hierarchy = 'created_at'
    readonly_fields = ('read_at', 'created_at', 'updated_at')
    ordering = ('-created_at',)
