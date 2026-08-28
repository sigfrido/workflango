# -*- coding: utf-8 -*-
"""
Optional drf-sebastian integration for workflango.

Not imported by any core workflango module, and not required to use
``workflango.drf`` -- opt in explicitly::

    # serializers.py
    from workflango.contrib.sebastian import SebastianWorkflowSerializerMixin

    class MyModelSerializer(SebastianWorkflowSerializerMixin, serializers.ModelSerializer):
        class Meta:
            model = MyModel
            fields = ['id', 'title', 'current_state']
        class Sebastian:
            list_fields = ['title', 'current_state_for_list']

    # views.py
    from sebastian.mixins import GUIMixin
    from workflango.contrib.sebastian import SebastianWorkflowViewSetMixin

    class MyModelViewSet(SebastianWorkflowViewSetMixin, GUIMixin, viewsets.ModelViewSet):
        queryset = MyModel.objects.all()
        serializer_class = MyModelSerializer

Requires ``djangorestframework`` and ``drf-sebastian`` both installed and configured
in the consuming project (``drf-sebastian`` is not published on PyPI -- install it
from its own repository). See ``docs/sebastian-integration.md`` for the full
walkthrough, including the four template fragments this module's
``template_namespace`` resolves to (already shipped at
``workflango/templates/workflango/sebastian/htmx/``).
"""

try:
    from sebastian.serializers import gui_field
except ImportError as e:
    raise ImportError(
        "drf-sebastian must be installed to use workflango.contrib.sebastian. "
        "Install it from its own repository (it is not published on PyPI)."
    ) from e

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response

from ..drf import WorkflowSerializerMixin, WorkflowViewSetMixin
from ..exceptions import TransitionNotAllowed, get_exception_error_msg
from ..i18n import wgettext_lazy
from ..wf_transition import WFTransitionDescriptor

__all__ = [
    'WorkflowActionSerializer',
    'SebastianWorkflowSerializerMixin',
    'SebastianWorkflowViewSetMixin',
]


class WorkflowActionSerializer(serializers.Serializer):  # pylint: disable=too-few-public-methods
    """
    Confirmation-form schema for a workflow transition, rendered by
    ``sebastian/htmx/confirm.html`` and validated on POST by
    ``SebastianWorkflowViewSetMixin.change_state_form``.

    The ``user`` field (impersonation) is intentionally excluded -- impersonation is a
    privileged API-level feature (see ``WorkflowViewSetMixin.change_state``), not
    exposed through this GUI confirm form.
    """
    phase     = serializers.CharField()
    owner     = serializers.IntegerField(allow_null=True, required=False, default=None)
    message   = serializers.CharField(allow_blank=True, required=False, default='')
    suspended = serializers.BooleanField(required=False, default=False)


class SebastianWorkflowSerializerMixin(WorkflowSerializerMixin):  # pylint: disable=too-few-public-methods
    """
    Drop-in replacement for ``workflango.drf.WorkflowSerializerMixin`` that adds a
    GUI-only ``current_state_for_list`` column and the ``__can_update`` flag
    sebastian's list/detail templates read to decide whether to show an edit link.
    """

    wf_datetime_format = 'SHORT_DATETIME_FORMAT'
    """
    Django format-variable name used to format ``State.state_date`` in the
    ``current_state_for_list`` badge.  Resolved locale-aware via
    ``django.utils.formats.date_format`` — not a strftime pattern.
    Override with another recognised name (e.g. ``'DATETIME_FORMAT'``) or a
    literal Django template-filter format string (e.g. ``'d/m/Y H:i'``).

    Deliberately distinct from ``GUISerializerMixin.datetime_format`` (a strftime
    pattern used by drf-sebastian to format DateTimeField values in the API
    response).  Setting this attribute does not affect those field renderings.
    """

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        request = self.context.get('request')
        if getattr(request, 'sebastian_gui', False):
            state = instance.wfm_state
            if state:
                impersonated_by = getattr(request, 'impersonated_by', None)
                ret['__can_update'] = state.owned_by(request.user, impersonated_by) and not state.suspended
            # No __can_update when unmanaged: template falls back to view.can_update() (True)
        return ret

    @gui_field(wgettext_lazy('State'))
    def current_state_for_list(self, obj):
        """Rendered as a Sebastian.list_fields column; never in the JSON API response."""
        from django.utils.formats import date_format
        from django.utils.html import format_html, conditional_escape
        from django.utils.safestring import mark_safe
        from django.utils.timezone import localtime
        state = obj.wfm_state
        if not state:
            return '—'
        date_str = date_format(localtime(state.state_date), self.wf_datetime_format) if state.state_date else ''
        owner_str = str(state.owner) if state.owner else '—'
        icons = ''
        if state.suspended:
            icons += '<i class="bi bi-hourglass-split ms-1 text-warning" title="Suspended"></i>'
        if state.message:
            icons += f'<i class="bi bi-sticky ms-1 text-muted" title="{conditional_escape(state.message)}"></i>'
        return format_html(
            '<span class="badge bg-secondary">{}</span>'
            ' <span class="ms-1">{}</span>'
            ' <small class="text-muted ms-1">{}</small>'
            '{}',
            state.phase or '—', owner_str, date_str, mark_safe(icons),
        )


class SebastianWorkflowViewSetMixin(WorkflowViewSetMixin):
    """
    Drop-in replacement for ``workflango.drf.WorkflowViewSetMixin`` that adds the
    GUI permission hooks and actions sebastian's ``GUIMixin``/renderer/router expect
    by naming convention (``can_update``/``can_delete``/``get_workflow_transitions``,
    the ``template_namespace`` used to resolve ``workflango/sebastian/{pack}/...``
    templates ahead of sebastian's own, and the ``history``/``change_state_form``
    GUI-flavored actions).

    Place before sebastian's ``GUIMixin`` in the MRO so these override its defaults::

        class MyModelViewSet(SebastianWorkflowViewSetMixin, GUIMixin, viewsets.ModelViewSet):
            ...
    """

    template_namespace = 'workflango'

    # ------------------------------------------------------------------
    # GUI permission hooks (override GUIMixin defaults)
    # ------------------------------------------------------------------

    def can_update(self):
        """Returns True only when the current user owns the workflow instance.

        In list context (_sebastian_obj not set) returns True so the per-row
        edit link is shown; ownership is enforced when the form actually loads.
        """
        obj = getattr(self, '_sebastian_obj', None)
        if obj is None:
            return True
        if not obj.wfm_state:
            return True   # object not yet under workflow management
        impersonated_by = getattr(self.request, 'impersonated_by', None)
        return obj.wfm.is_owner(self.request.user, impersonated_by) and not obj.wfm_state.suspended

    def can_delete(self):
        """Workflow-managed objects cannot be deleted via the GUI."""
        return False

    def get_workflow_transitions(self, instance):
        """
        Returns WorkflowTransitions(phase_transitions, reject_transition, command_transitions)
        for the given instance and the current request user.

        sebastian's renderer duck-types on this method and, if present, injects the
        result into the template context as ``workflow_transitions`` so the
        ``workflango/sebastian/htmx/detail.html`` template can render the action buttons.
        """
        return WFTransitionDescriptor.get_workflow_transitions(instance, self.request.user)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

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
        'label': wgettext_lazy('History'),
        'icon': 'clock-history',
        'position': 'both',
    }

    @action(detail=True, methods=['get', 'post'])
    def change_state_form(self, request, pk=None, **__):  # noqa: ARG002
        """
        GET: returns the inline confirmation form for a workflow transition.
             Accepts ``?phase=<phase>`` query parameter.
        POST: performs the transition and returns the instance detail data so
              HTMX can reload the full detail page into ``#sebastian-content``.

        Both GET and POST render through the workflango confirm template when
        present, falling back to the base Sebastian confirm template.
        """
        instance = self.get_object()
        self._sebastian_obj = instance

        if request.method == 'GET':
            phase = request.query_params.get('phase')
            if not phase:
                raise DRFValidationError({'phase': 'Required.'})

            transition = WFTransitionDescriptor(instance, phase, request.user)
            owner_choices = transition.get_potential_owners() if transition.show_owner else []
            default_owner = transition.get_default_owner() if transition.show_owner else None
            severity_to_style = {'info': 'primary', 'warn': 'warning', 'error': 'danger'}

            pre_check_blocked = not transition.allowed()
            pre_check_errors = (
                [getattr(transition, 'error_msg', 'Transition not allowed.')]
                if pre_check_blocked else []
            )

            response_data = {
                'action': 'confirm',
                'confirm_prompt': transition.caption,
                'confirm_style': severity_to_style.get(transition.severity, 'primary'),
                'action_url': request.path,
                'confirm_serializer': WorkflowActionSerializer(initial={
                    'phase': phase,
                    'suspended': transition.is_suspend,
                }),
                'owner_choices': owner_choices,
                'default_owner_id': default_owner.pk if default_owner else None,
                'show_owner': transition.show_owner,
                'require_message': transition.require_message,
                'phase': phase,
                'suspended': transition.is_suspend,
                'pre_check_blocked': pre_check_blocked,
                'warnings': instance.wfm.warnings,
                'infos': instance.wfm.infos,
            }
            if pre_check_errors:
                response_data['form_errors'] = {'non_field_errors': pre_check_errors}
            return Response(response_data)

        # POST: perform the transition
        input_ser = WorkflowActionSerializer(data=request.data)
        input_ser.is_valid(raise_exception=True)
        data = input_ser.validated_data

        self.check_wf_permission(instance, request.user)

        # Resolve command strings ('suspend', 'resume', 'release', 'take-ownership', ...)
        # to the real destination phase and suspended flag via WFTransitionDescriptor.
        phase      = data['phase']
        transition = WFTransitionDescriptor(instance, phase, request.user)
        destination = transition.destination
        suspended   = transition.is_suspend

        form_errors: dict = {}

        if data['owner']:
            try:
                owner = get_user_model().objects.get(pk=data['owner'], is_active=True)
            except ObjectDoesNotExist:
                form_errors['owner'] = [f"User {data['owner']} not found."]
                owner = None
        else:
            owner = transition.owner

        if not form_errors:
            impersonated_by = getattr(request, 'impersonated_by', None)
            try:
                instance.wfm.transition(
                    request.user,
                    destination,
                    owner,
                    message=data['message'],
                    suspended=suspended,
                    impersonated_by=impersonated_by,
                )
            except (TransitionNotAllowed, ValidationError) as e:
                form_errors['non_field_errors'] = [get_exception_error_msg(e)]

        if form_errors:
            owner_choices = transition.get_potential_owners() if transition.show_owner else []
            default_owner = transition.get_default_owner() if transition.show_owner else None
            severity_to_style = {'info': 'primary', 'warn': 'warning', 'error': 'danger'}
            response = Response({
                'action':          'confirm',
                'confirm_prompt':  transition.caption,
                'confirm_style':   severity_to_style.get(transition.severity, 'primary'),
                'action_url':      request.path,
                'owner_choices':   owner_choices,
                'default_owner_id': default_owner.pk if default_owner else None,
                'show_owner':      transition.show_owner,
                'require_message': transition.require_message,
                'phase':           phase,
                'suspended':       transition.is_suspend,
                'form_errors':     form_errors,
            }, status=400)
            response['X-Sebastian-Form-Error'] = '1'
            response['HX-Retarget'] = '#wf-confirm-panel'
            response['HX-Reswap'] = 'innerHTML'
            return response

        instance.refresh_from_db()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    change_state_form.gui_url = True  # register in GUIRouter without adding to action buttons
