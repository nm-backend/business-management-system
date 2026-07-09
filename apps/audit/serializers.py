from rest_framework import serializers
from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    """
    Serializer отдаёт audit_logs только на чтение.

    Журнал действий нельзя создавать или менять через API: записи появляются
    только из backend-сервиса write_audit_log(), чтобы пользователь не мог
    подделать историю операций.
    """

    class Meta:
        model = AuditLog
        fields = [
            'id',
            'actor',
            'actor_username',
            'actor_role',
            'action',
            'object_type',
            'object_id',
            'object_repr',
            'changes',
            'metadata',
            'ip_address',
            'user_agent',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields
