from rest_framework.permissions import BasePermission

class IsOwner(BasePermission):
    """Allow access only to users with 'owner' role."""
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == 'owner'
        )

class IsAdmin(BasePermission):
    """Allow access only to users with 'admin' role."""
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == 'admin'
        )

class IsWorker(BasePermission):
    """Allow access only to users with 'worker' role."""
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == 'worker'
        )

class IsOwnerOrAdmin(BasePermission):
    """Allow access to users with 'owner' or 'admin' role."""
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role in ('owner', 'admin')
        )

class IsOwnerOrAdminOrWorker(BasePermission):
    """Allow access to all authenticated users with a valid role."""
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role in ('owner', 'admin', 'worker')
        )

class FinancialDataPermission(BasePermission):
    """Only owner can access financial data."""
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == 'owner'
        )
