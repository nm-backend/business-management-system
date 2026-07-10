from .models import AuditLog
from .services import collect_model_changes, write_audit_log


class AuditCreateUpdateMixin:
    def perform_create(self, serializer):
        instance = serializer.save()
        write_audit_log(
            action=AuditLog.Action.CREATE,
            actor=self.request.user,
            target=instance,
            request=self.request,
        )

    def perform_update(self, serializer):
        changes = collect_model_changes(
            serializer.instance,
            serializer.validated_data,
        )
        instance = serializer.save()
        if changes:
            write_audit_log(
                action=AuditLog.Action.UPDATE,
                actor=self.request.user,
                target=instance,
                changes=changes,
                request=self.request,
            )


class AuditedArchiveMixin(AuditCreateUpdateMixin):
    def perform_destroy(self, instance):
        instance.archive()
        write_audit_log(
            action=AuditLog.Action.ARCHIVE,
            actor=self.request.user,
            target=instance,
            request=self.request,
        )
