class ActionSerializerMixin:
    serializer_action_classes = {}

    def get_serializer_class(self):
        serializer_class = self.serializer_action_classes.get(self.action)
        if serializer_class is not None:
            return serializer_class
        return super().get_serializer_class()


class OwnerSerializerMixin:
    owner_serializer_class = None

    def get_serializer_class(self):
        if (
            self.owner_serializer_class is not None
            and self.request.user.is_authenticated
            and self.request.user.is_owner
        ):
            return self.owner_serializer_class
        return super().get_serializer_class()


class ReadWritePermissionMixin:
    write_actions = frozenset({"create", "update", "partial_update", "destroy"})
    read_permission_classes = ()
    write_permission_classes = ()

    def get_permissions(self):
        permission_classes = (
            self.write_permission_classes
            if self.action in self.write_actions
            else self.read_permission_classes
        )
        if not permission_classes:
            return super().get_permissions()
        return [permission_class() for permission_class in permission_classes]


class HideArchivedFromNonOwnersMixin:
    def get_queryset(self):
        queryset = super().get_queryset()
        if not (
            self.request.user.is_authenticated and self.request.user.is_owner
        ):
            queryset = queryset.filter(is_archived=False)
        return queryset
