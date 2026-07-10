"""
Views for production API.

Этот модуль содержит API views для управления задачами и работами
с защитой финансовых данных для non-owner пользователей.
"""
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from apps.core.permissions import IsOwnerOrAdmin
from .models import Task, WorkRecord, TaskStatus
from .serializers import (
    TaskSerializer, TaskCreateSerializer,
    WorkRecordSerializer, WorkRecordLimitedSerializer, WorkRecordCreateSerializer
)


class TaskViewSet(viewsets.ModelViewSet):
    """
    ViewSet для управления задачами.

    Разные права доступа для разных ролей:
    - Owner: полный доступ
    - Admin: может создавать и назначать задачи
    - Worker: видит только свои задачи
    """
    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            return [IsOwnerOrAdmin()]
        return [IsAuthenticated()]

    def get_serializer_class(self):
        """
        Возвращает сериализатор в зависимости от действия.
        """
        if self.action == 'create':
            return TaskCreateSerializer
        return TaskSerializer

    def get_queryset(self):
        """
        Возвращает queryset задач.

        Worker видит только свои задачи, остальные - все.
        """
        queryset = Task.objects.select_related('worker', 'assigned_by', 'order')
        request = self.request

        if request.user and request.user.is_worker:
            queryset = queryset.filter(worker=request.user)

        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        return queryset

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed('DELETE', detail='Task deletion is prohibited.')

    @action(detail=True, methods=['post'])
    def accept(self, request, pk=None):
        """
        Работник принимает задачу.

        POST /api/v1/production/tasks/{id}/accept/
        """
        task = self.get_object()
        if task.worker != request.user:
            return Response(
                {'detail': 'You can only accept your own tasks'},
                status=status.HTTP_403_FORBIDDEN
            )

        task.status = TaskStatus.ACCEPTED
        task.accepted_at = timezone.now()
        task.save()

        serializer = self.get_serializer(task)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def refuse(self, request, pk=None):
        """
        Работник отказывается от задачи.

        POST /api/v1/production/tasks/{id}/refuse/
        Body: {"reason": "material_insufficient", "comment": "..."}
        """
        task = self.get_object()
        if task.worker != request.user:
            return Response(
                {'detail': 'You can only refuse your own tasks'},
                status=status.HTTP_403_FORBIDDEN
            )

        reason = request.data.get('reason')
        comment = request.data.get('comment', '')

        if not reason:
            return Response(
                {'detail': 'reason is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        task.status = TaskStatus.REFUSED
        task.refusal_reason = reason
        task.refusal_comment = comment
        task.save()

        serializer = self.get_serializer(task)
        return Response(serializer.data)


class WorkRecordViewSet(viewsets.ModelViewSet):
    """
    ViewSet для управления записями о работе.

    Разные сериализаторы для разных ролей:
    - Owner: полный доступ с финансовыми данными
    - Admin/Worker: ограниченный доступ без финансовых данных
    """
    def get_permissions(self):
        if self.action == 'create':
            return [IsAuthenticated()]
        if self.action in ('update', 'partial_update', 'destroy'):
            return [IsOwnerOrAdmin()]
        return [IsAuthenticated()]

    def get_serializer_class(self):
        """
        Возвращает сериализатор в зависимости от роли пользователя.

        Owner получает полные данные, остальные - ограниченные.
        """
        if self.action == 'create':
            return WorkRecordCreateSerializer

        request = self.request
        if request.user and request.user.is_owner:
            return WorkRecordSerializer
        return WorkRecordLimitedSerializer

    def get_queryset(self):
        """
        Возвращает queryset записей о работе.

        Worker видит только свои работы, остальные - все.
        """
        queryset = WorkRecord.objects.select_related('worker', 'product', 'confirmed_by')
        request = self.request

        if request.user and request.user.is_worker:
            queryset = queryset.filter(worker=request.user)

        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        return queryset

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed('DELETE', detail='Work-record deletion is prohibited.')

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        """
        Подтверждает выполненную работу.

        POST /api/v1/production/works/{id}/confirm/
        Body: {"labor_cost": 1000}
        """
        work = self.get_object()
        if not (request.user.is_owner or request.user.is_admin):
            return Response(
                {'detail': 'Only owner or admin can confirm work'},
                status=status.HTTP_403_FORBIDDEN
            )

        work.status = WorkRecord.WorkStatus.CONFIRMED
        work.confirmed_by = request.user
        work.confirmed_at = timezone.now()

        if request.user.is_owner:
            labor_cost = request.data.get('labor_cost', 0)
            work.labor_cost = labor_cost

        work.save()
        serializer = self.get_serializer(work)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """
        Отклоняет выполненную работу.

        POST /api/v1/production/works/{id}/reject/
        Body: {"reason": "..."}
        """
        work = self.get_object()
        if not (request.user.is_owner or request.user.is_admin):
            return Response(
                {'detail': 'Only owner or admin can reject work'},
                status=status.HTTP_403_FORBIDDEN
            )

        reason = request.data.get('reason', '')
        work.status = WorkRecord.WorkStatus.REJECTED
        work.rejection_reason = reason
        work.save()

        serializer = self.get_serializer(work)
        return Response(serializer.data)
