# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.decorators import method_decorator

from .exceptions import get_exception_error_msg


# ---------------------------------------------------------------------------
# Generic CBV mixins (moved from compat.py)
# ---------------------------------------------------------------------------

class LoginRequiredMixin:
    """Redirect unauthenticated users to the login page."""

    @method_decorator(login_required)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)


class AccessDeniedMixin:
    """
    Mixin that checks access before dispatching a view.

    Override access_denied_error() to return a non-empty error string when
    the request should be blocked. The mixin redirects to access_denied_url,
    access_denied_view (resolved via reverse()), or the setting
    WORKFLANGO_ACCESS_DENIED_URL (default '/').
    """

    access_denied_url = None
    access_denied_view = None

    @method_decorator(login_required)
    def dispatch(self, request, *args, **kwargs):
        self.request = request
        self.kwargs = kwargs
        msg = self.access_denied_error(request, *args, **kwargs)
        if msg:
            return self.access_denied_redirect(msg)
        return super().dispatch(request, *args, **kwargs)

    def access_denied_error(self, request, *args, **kwargs):
        return ''

    def get_access_denied_url(self):
        if self.access_denied_url:
            return self.access_denied_url
        if self.access_denied_view:
            return reverse(self.access_denied_view)
        return None

    def access_denied_redirect(self, error_msg=''):
        if error_msg:
            messages.add_message(self.request, messages.ERROR, error_msg)
        redirect_url = self.get_access_denied_url()
        if redirect_url:
            return HttpResponseRedirect(redirect_url)
        return HttpResponseRedirect(getattr(settings, 'WORKFLANGO_ACCESS_DENIED_URL', '/'))


class CachedGetObjectMixin:
    """Cache the result of get_object() within a single request."""

    def get_object(self):
        if not getattr(self, '_obj_cached', None):
            self._obj_cached = super().get_object()
        return self._obj_cached


# ---------------------------------------------------------------------------
# Workflow-specific view mixins
# ---------------------------------------------------------------------------

class _WorkflowContextMixin:
    """Inject workflow transition data into the template context for detail views."""

    def get_workflow_context(self, context):
        context['allowed_transitions'], context['reject_transition'] = self.get_allowed_transitions()
        context['is_admin'] = self.get_object().wfm.can_admin(self.request.user)
        return context

    def get_allowed_transitions(self):
        """
        Return (transitions, reject_transition) for the object's current state.

        transitions — list of WFTransitionDescriptor for forward/non-reject moves.
        reject_transition — WFTransitionDescriptor for the reject action, or None.
        """
        obj = self.get_object()
        cur_state = obj.current_state
        prev_state = cur_state.get_previous_state()
        cfg = cur_state.wfm_state_config()
        transitions = []
        reachable_states = cfg['reachable_states'].keys()
        if cur_state.can_reject and prev_state.phase == cur_state.phase:
            rej_trans = obj.wfm.get_transition(cur_state.phase, self.request.user, cur_state.user)
        else:
            rej_trans = None
        for dest_state in reachable_states:
            transition = obj.wfm.get_transition(dest_state, self.request.user)
            if transition.is_reject and prev_state and (transition.destination == prev_state.phase):
                if cur_state.can_reject:
                    rej_trans = transition
            elif not transition.is_reject or cur_state.find_last_state(transition.destination):
                transitions.append(transition)
        return transitions, rej_trans


class _BaseWorkflowTransitionMixin:
    """
    Base mixin for views that perform a workflow state transition on form submit.

    Provides check_and_transition() which calls obj.wfm.transition() and hooks
    before_transition() / after_transition() for customisation.

    form_valid() and forms_valid() both call check_and_transition().
    forms_valid() is the django-extra-views counterpart for views with inline
    formsets; it is a no-op if django-extra-views is not used.
    """

    destination_state = None
    destination_owner = None
    destination_suspended = False
    transition_message = ""
    force_transition_type = None

    def get_destination_owner(self):
        return self.destination_owner

    def get_destination_state(self):
        return self.destination_state

    def get_transition_message(self):
        return self.transition_message

    def get_destination_suspended(self):
        return self.destination_suspended

    def get_force_transition_type(self):
        return self.force_transition_type

    def check_and_transition(self):
        if getattr(self, 'transitioned', 0):
            # Guard against double-call: form_valid and forms_valid may both fire.
            return
        destination_state = self.get_destination_state()
        destination_owner = self.get_destination_owner()
        transition_message = self.get_transition_message()
        suspended = self.get_destination_suspended()
        force_transition_type = self.get_force_transition_type()
        obj = self.object
        try:
            self.before_transition(obj)
            new_state = obj.wfm.transition(
                self.request.user, destination_state, destination_owner,
                message=transition_message, suspended=suspended,
                force_transition_type=force_transition_type,
            )
            self.after_transition(new_state)
            setattr(self, 'transitioned', 1)
        except Exception as e:
            self.transition_denied()
            messages.add_message(
                self.request, messages.ERROR,
                f"Il passaggio a {destination_state} non è stato effettuato: {get_exception_error_msg(e)}.",
            )
            transaction.set_rollback(True)

    def before_transition(self, obj):
        pass

    def after_transition(self, new_state):
        messages.add_message(self.request, messages.INFO, f"Passaggio di stato effettuato: {new_state.phase}")

    def check_transition_is_valid(self):
        """
        Validate the transition without performing it. Call this before rendering
        the transition form to catch validation errors early.
        """
        instance = self.get_object()
        destination_state = self.get_destination_state()
        new_owner = self.get_destination_owner()
        suspended = self.get_destination_suspended()
        try:
            instance.full_clean()
            instance.wfm.run_transition_validations(
                self.request.user, instance.current_state, destination_state, new_owner, suspended,
            )
            return True
        except ValidationError as e:
            if self.object.wfm.can_admin(self.request.user) and self.get_destination_owner() == self.request.user:
                messages.add_message(
                    self.request, messages.WARNING,
                    f"Il passaggio di stato verrà effettuato come ADMIN, sono stati rilevati i seguenti errori: {get_exception_error_msg(e)}.",
                )
                return True
            messages.add_message(
                self.request, messages.ERROR,
                f"Impossibile effettuare il passaggio di stato: {get_exception_error_msg(e)}.",
            )
            return False
        except Exception as e:
            messages.add_message(self.request, messages.ERROR, f"Errore inatteso: {get_exception_error_msg(e)}.")
            return False

    def transition_denied(self):
        pass

    @method_decorator(transaction.atomic)
    def form_valid(self, form):
        out = super().form_valid(form)
        if not getattr(self, 'object', None):
            self.object = self.get_object()
        self.check_and_transition()
        return out

    @method_decorator(transaction.atomic)
    def forms_valid(self, form, inlines):
        """django-extra-views counterpart of form_valid() for views with inline formsets."""
        out = super().forms_valid(form, inlines)
        if not getattr(self, 'object', None):
            self.object = self.get_object()
        self.check_and_transition()
        return out


class WorkflowModelChangeState(AccessDeniedMixin, _BaseWorkflowTransitionMixin, _WorkflowContextMixin):
    """
    Mixin for a view where either the owner or an admin can change the workflow state.
    """

    def access_denied_error(self, request, *args, **kwargs):
        obj = self.get_object()
        if obj.wfm.is_owner(request.user):
            return ''
        if obj.current_state.owner:
            req = obj.wfm.can_admin(request.user)
        else:
            req = obj.wfm.can_edit(request.user)
        if not req:
            return "L'utente non può accedere a questa risorsa."


class WorkflowModelCreate(AccessDeniedMixin, _BaseWorkflowTransitionMixin):
    """Mixin for a create view that checks whether the user can create new workflow objects."""

    def access_denied_error(self, request, *args, **kwargs):
        if not self.model.wfm_config.can_create(request.user):
            return "Errore di accesso: non hai i privilegi di creazione."


class WorkflowModelList(LoginRequiredMixin):
    """
    Mixin for a list view that exposes active workflow states to the template context.

    Note: filtering by read permission is commented out because it is slow on large
    datasets. Re-implement with a wfm_state/history filter if needed.
    """

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        context['active_states'] = self.model.wfm_config.get_states_list(closed=False)
        context['active_states_filter'] = '&'.join(
            [f"search_fase={state}" for state in context['active_states']]
        )
        return context

    def get_queryset(self):
        qset = super().get_queryset()
        qset = qset.exclude(wfm_state=None)
        return qset


class WorkflowModelUpdate(AccessDeniedMixin, _WorkflowContextMixin):
    """Mixin for an update view restricted to the current owner of the workflow object."""

    def access_denied_error(self, request, *args, **kwargs):
        obj = self.get_object()
        if not obj.wfm.is_owner(request.user):
            return "L'utente non può accedere a questa risorsa."
        cur_state = obj.current_state
        if cur_state and cur_state.suspended:
            return "Il record è sospeso. Impossibile procedere."


class WorkflowDetailMixin(CachedGetObjectMixin, AccessDeniedMixin, _WorkflowContextMixin):
    """
    Mixin for a detail view of a workflow-managed object.

    Adds to context:
    - wf_editable: the object can be edited by the current user
    - wf_admin_owned: the user is both owner and admin
    - wf_can_take_ownership: the user can take ownership
    - wf_can_delete: the user can delete the object
    - wf_edit_button_label: label for the edit button (empty if not editable)
    - allowed_transitions, reject_transition, is_admin (from _WorkflowContextMixin)

    Also marks the object as read/unread when ?unread=0|1 is passed.
    """

    def access_denied_error(self, request, *args, **kwargs):
        if not self.get_object().wfm.can_read(request.user):
            return "L'utente non può visualizzare questa risorsa."

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        instance = context['object']
        st = instance.current_state
        user = self.request.user
        if st.owner == user:
            try:
                unread = bool(int(self.request.GET.get('unread', 0)))
            except Exception:
                unread = False
            if st.unread != unread:
                st.unread = unread
                st.save()
                messages.add_message(
                    self.request, messages.INFO,
                    f"L'oggetto è stato impostato come {'da leggere' if unread else 'già letto'}.",
                )

        wf_editable = instance.wfm.is_owner(user) and not st.suspended and not st.get_state_property('disable_editing')
        wf_admin_owned = instance.wfm.is_owner(user) and instance.wfm.can_admin(user)
        context['wf_can_take_ownership'] = instance.wfm.can_take_ownership(user)
        context['wf_editable'] = wf_editable
        context['wf_admin_owned'] = wf_admin_owned
        context['wf_can_delete'] = self.wf_can_delete(user, instance)
        context['wf_edit_button_label'] = st.get_state_property('edit_button_label') if wf_editable else ''

        return self.get_workflow_context(context)

    def wf_can_delete(self, user, instance):
        return not instance.user_can_delete_error(user)
