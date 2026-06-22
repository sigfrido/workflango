# -*- coding: utf-8 -*-
"""
Django REST Framework integration for workflango.

Requires ``djangorestframework`` to be installed in the consuming project.

Typical usage::

    # serializers.py
    from workflango.drf import WorkflowSerializerMixin

    class MyModelSerializer(WorkflowSerializerMixin, serializers.ModelSerializer):
        class Meta:
            model = MyModel
            fields = ['id', 'title', 'current_state']

    # views.py
    from workflango.drf import WorkflowViewSetMixin, WorkflowFilterBackend

    class MyModelViewSet(WorkflowViewSetMixin, ModelViewSet):
        queryset = MyModel.objects.all()
        serializer_class = MyModelSerializer
        filter_backends = [WorkflowFilterBackend]

        def get_queryset(self):
            # Scope results to the effective user when ?as_user= is specified
            acting_user, _ = self.get_effective_user(self.request)
            return MyModel.objects.filter(wfm_state__owner=acting_user)
"""

try:
    from rest_framework import serializers, status
    from rest_framework.decorators import action
    from rest_framework.exceptions import PermissionDenied
    from rest_framework.exceptions import ValidationError as DRFValidationError
    from rest_framework.response import Response
except ImportError as e:
    raise ImportError(
        "djangorestframework must be installed to use workflango.drf. "
        "Add 'djangorestframework' to your project dependencies."
    ) from e

try:
    from sebastian.serializers import gui_field
except ImportError:
    def gui_field(label_or_func=None):  # no-op fallback when sebastian is not installed
        if callable(label_or_func):
            return label_or_func
        return lambda f: f

from django.contrib.auth.models import User
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError

from .exceptions import TransitionNotAllowed, get_exception_error_msg
from .filters import WorkflowFilterBackend  # re-exported for convenience
from .models import State

__all__ = [
    'StateSerializer',
    'WorkflowSerializerMixin',
    'WorkflowViewSetMixin',
    'WorkflowFilterBackend',
    'gui_field',
]


class StateSerializer(serializers.ModelSerializer):
    """
    Read-only serializer for a State instance.

    Exposes FK ids (owner_id, user_id, impersonated_by_id) plus display strings
    derived from __str__ of the related objects. Suitable for embedding as
    current_state inline or for history lists.

    For performance, prefetch related users when serializing many states::

        states = instance.wfm.get_states().select_related('owner', 'user', 'impersonated_by')
    """
    transition_type_display = serializers.SerializerMethodField()
    owner_display = serializers.SerializerMethodField()
    user_display = serializers.SerializerMethodField()
    impersonated_by_display = serializers.SerializerMethodField()

    class Meta:
        model = State
        fields = [
            'id', 'phase', 'state_date',
            'owner_id', 'owner_display',
            'user_id', 'user_display',
            'transition_type', 'transition_type_display',
            'suspended', 'unread', 'message',
            'impersonated_by_id', 'impersonated_by_display',
            'snapshot',
        ]
        read_only_fields = fields

    def get_transition_type_display(self, obj):  # noqa: D102
        return obj.transition_type_display()

    def get_owner_display(self, obj):  # noqa: D102
        return str(obj.owner) if obj.owner else None

    def get_user_display(self, obj):  # noqa: D102
        return str(obj.user) if obj.user else None

    def get_impersonated_by_display(self, obj):  # noqa: D102
        return str(obj.impersonated_by) if obj.impersonated_by else None


class WorkflowSerializerMixin(serializers.Serializer):  # pylint: disable=too-few-public-methods
    """
    Serializer mixin that adds a read-only ``current_state`` nested field and a
    GUI-only ``current_state_for_list`` column to any WorkflowModel serializer.

    Usage::

        class MyWorkflowModelSerializer(WorkflowSerializerMixin, serializers.ModelSerializer):
            class Meta:
                model = MyWorkflowModel
                fields = ['id', 'title', 'current_state']

    To use a custom StateSerializer subclass, redeclare ``current_state`` on the
    consuming serializer.

    ``current_state_for_list`` is a ``@gui_field`` method — it renders the workflow
    state as a formatted HTML badge for use in ``Sebastian.list_fields``. It is
    never included in the JSON API response.
    """

    current_state = StateSerializer(read_only=True)
    datetime_format = '%d/%m/%Y %H:%M'

    @gui_field('Stato')
    def current_state_for_list(self, obj):
        from django.utils.html import format_html
        from django.utils.timezone import localtime
        state = obj.wfm_state
        if not state:
            return '—'
        date_str = localtime(state.state_date).strftime(self.datetime_format) if state.state_date else ''
        owner_str = str(state.owner) if state.owner else '—'
        return format_html(
            '<span class="badge bg-secondary">{}</span>'
            ' <span class="ms-1">{}</span>'
            ' <small class="text-muted ms-1">{}</small>',
            state.phase or '—', owner_str, date_str,
        )


class _MarkReadInputSerializer(serializers.Serializer):  # pylint: disable=too-few-public-methods
    """Input schema for the mark_read action."""
    read = serializers.BooleanField(default=True)


class _ChangeStateInputSerializer(serializers.Serializer):  # pylint: disable=too-few-public-methods
    """Input schema for the change_state action."""
    phase = serializers.CharField()
    owner = serializers.IntegerField(allow_null=True, default=None)
    user = serializers.IntegerField(allow_null=True, default=None,
                                    help_text="Utente per cui agire (impersonazione). "
                                              "Se omesso o uguale al chiamante, nessuna impersonazione.")
    message = serializers.CharField(allow_blank=True, default='')
    suspended = serializers.BooleanField(default=False)


class WorkflowViewSetMixin:
    """
    ViewSet mixin that adds standard workflow actions to any ModelViewSet.

    When used alongside a Sebastian GUIMixin, sets ``template_namespace = 'workflango'``
    so the Sebastian renderer picks up templates from
    ``workflango/sebastian/{pack}/`` instead of the default ``sebastian/{pack}/``.

    Actions added:
    - GET  ``/{pk}/workflow_history/``  — ordered list of all State records
    - POST ``/{pk}/change_state/``      — perform a workflow transition

    Impersonation:
    - POST ``change_state`` accepts an optional ``user`` field in the body.
      If ``user != request.user`` and the caller is allowed to impersonate,
      the transition is recorded as ``user`` acting, ``request.user`` as ``impersonated_by``.
    - GET endpoints accept ``?as_user=<id>`` to resolve the effective user.
      The consuming ViewSet can call ``get_effective_user(request)`` in ``get_queryset()``
      to scope results accordingly.

    Impersonation is disabled by default. Enable globally with::

        WORKFLANGO_ALLOW_IMPERSONATE = True  # in settings.py

    Override ``get_impersonable_users(user)`` to customise who can be impersonated by whom.

    Usage::

        class MyModelViewSet(WorkflowViewSetMixin, ModelViewSet):
            queryset = MyModel.objects.all()
            serializer_class = MyModelSerializer
            filter_backends = [WorkflowFilterBackend]
    """

    template_namespace = 'workflango'

    state_serializer_class = StateSerializer

    def get_state_serializer(self, *args, **kwargs):  # noqa: D102
        return self.state_serializer_class(*args, **kwargs)

    def get_workflow_config(self):
        """Returns the ``WorkflowConfig`` for the model managed by this ViewSet."""
        return self.queryset.model.wfm_config

    # ------------------------------------------------------------------
    # Impersonation helpers
    # ------------------------------------------------------------------

    def get_impersonable_users(self, user):
        """
        Returns a queryset of users that ``user`` is allowed to impersonate.

        Delegates to ``WorkflowConfig.get_impersonable_users(user)``, which
        applies the default policy (superuser / WORKFLOW_ADMIN_GROUP) unless
        the workflow was configured with a custom ``impersonable_users`` callable.

        Override this method on the ViewSet to bypass the WorkflowConfig lookup.
        """
        return self.get_workflow_config().get_impersonable_users(user)

    def resolve_acting_user(self, request, user_id=None):
        """
        Resolves the acting user and impersonation context for a request.

        Returns ``(acting_user, impersonated_by)`` where:
        - ``acting_user`` is who the operation will be attributed to
        - ``impersonated_by`` is the real caller (or None if no impersonation)

        Raises ``PermissionDenied`` if ``user_id`` is specified but the caller
        is not allowed to impersonate that user, or if impersonation is disabled
        globally (``WORKFLANGO_ALLOW_IMPERSONATE`` not True in settings).
        """
        if not user_id or user_id == request.user.pk:
            return request.user, None

        if not getattr(settings, 'WORKFLANGO_ALLOW_IMPERSONATE', False):
            raise PermissionDenied("Impersonazione non abilitata (WORKFLANGO_ALLOW_IMPERSONATE).")

        try:
            target_user = User.objects.get(pk=user_id, is_active=True)
        except ObjectDoesNotExist as exc:
            raise DRFValidationError({'user': f'Utente {user_id} non trovato o non attivo.'}) from exc

        if not self.get_impersonable_users(request.user).filter(pk=user_id).exists():
            raise PermissionDenied(f'Non autorizzato a operare come {target_user}.')

        return target_user, request.user

    def get_effective_user(self, request):
        """
        Resolves the effective user from the ``?as_user=<id>`` query parameter.

        Returns ``(acting_user, impersonated_by)`` — same contract as
        ``resolve_acting_user``. Intended for use in ``get_queryset()`` to scope
        list results to what the acting user would see::

            def get_queryset(self):
                acting_user, _ = self.get_effective_user(self.request)
                return MyModel.objects.filter(wfm_state__owner=acting_user)
        """
        as_user_id = request.query_params.get('as_user')
        if not as_user_id:
            return request.user, None
        try:
            as_user_id = int(as_user_id)
        except (ValueError, TypeError) as exc:
            raise DRFValidationError({'as_user': 'Valore non valido: atteso intero.'}) from exc
        return self.resolve_acting_user(request, as_user_id)

    # ------------------------------------------------------------------
    # Permission check
    # ------------------------------------------------------------------

    def check_wf_permission(self, instance, acting_user):
        """
        Raises ``PermissionDenied`` if ``acting_user`` is neither owner nor admin
        of the workflow instance. Skipped for unmanaged objects (first transition).
        """
        if not instance.wfm_state:
            return
        if not instance.wfm.is_owner(acting_user) and not instance.wfm.can_admin(acting_user):
            raise PermissionDenied("Accesso negato: utente non è proprietario né amministratore.")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    @action(detail=True, methods=['get'])
    def workflow_history(self, request, pk=None):  # noqa: ARG002
        """Returns all State records for this instance, oldest first."""
        instance = self.get_object()
        states = instance.wfm.get_states().select_related('owner', 'user', 'impersonated_by')
        page = self.paginate_queryset(states)
        if page is not None:
            serializer = self.get_state_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_state_serializer(states, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def history(self, request, pk=None, **kwargs):  # noqa: ARG002
        """Returns all State records for this instance (GUI-friendly alias for workflow_history)."""
        instance = self.get_object()
        self._sebastian_obj = instance
        states = instance.wfm.get_states().select_related('owner', 'user', 'impersonated_by')
        page = self.paginate_queryset(states)
        if page is not None:
            serializer = self.get_state_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_state_serializer(states, many=True)
        return Response(serializer.data)

    history.gui_config = {
        'label': 'Storico',
        'icon': 'clock-history',
        'position': 'both',
    }

    @action(detail=True, methods=['post'])
    def change_state(self, request, pk=None):  # noqa: ARG002
        """
        Perform a workflow transition.

        Request body::

            {
                "phase":     "nuova_fase",
                "owner":     42,     // user id; null or omitted = no owner
                "user":      15,     // optional: act as this user (impersonation)
                "message":   "...",  // optional
                "suspended": false   // optional
            }

        If ``user`` differs from the caller, the caller is saved in
        ``State.impersonated_by`` and ``user`` becomes the recorded actor.

        Returns the new State (201) on success.
        Returns 400 on validation / transition failure.
        Returns 403 if not owner/admin, or impersonation is not allowed.
        """
        instance = self.get_object()

        input_ser = _ChangeStateInputSerializer(data=request.data)
        input_ser.is_valid(raise_exception=True)
        data = input_ser.validated_data

        acting_user, impersonated_by = self.resolve_acting_user(request, data['user'])
        self.check_wf_permission(instance, acting_user)

        owner = None
        if data['owner']:
            try:
                owner = User.objects.get(pk=data['owner'], is_active=True)
            except ObjectDoesNotExist as exc:
                raise DRFValidationError({'owner': f"Utente {data['owner']} non trovato."}) from exc

        try:
            new_state = instance.wfm.transition(
                acting_user,
                data['phase'],
                owner,
                message=data['message'],
                suspended=data['suspended'],
                impersonated_by=impersonated_by,
            )
        except (TransitionNotAllowed, ValidationError) as e:
            raise DRFValidationError({'detail': get_exception_error_msg(e)}) from e

        serializer = self.get_state_serializer(new_state)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):  # noqa: ARG002
        """
        Set or clear the ``unread`` flag on the current state.

        Only the current owner (or an impersonated user acting as owner) may call
        this endpoint.  Intended for two patterns:

        1. **Auto mark-read**: the detail template fires a delayed POST after a few
           seconds with ``{"read": true}`` (or no body, default is ``true``).
        2. **Toggle button**: the client sends the desired state explicitly::

               {"read": true}   # mark as read   → unread becomes False
               {"read": false}  # mark as unread  → unread becomes True

        Returns ``{"unread": <bool>}`` so the client can update its UI without a
        full page reload.

        Returns 403 if the caller is not the current owner.
        Returns 404 if the instance has no active state yet.
        """
        instance = self.get_object()
        current_state = instance.wfm_state
        if not current_state:
            raise PermissionDenied("L'oggetto non ha ancora uno stato attivo.")

        acting_user, _ = self.get_effective_user(request)
        if current_state.owner_id != acting_user.pk:
            raise PermissionDenied("Solo il proprietario corrente può modificare lo stato di lettura.")

        input_ser = _MarkReadInputSerializer(data=request.data)
        input_ser.is_valid(raise_exception=True)
        current_state.unread = not input_ser.validated_data['read']
        current_state.save(update_fields=['unread'])
        return Response({'unread': current_state.unread})
