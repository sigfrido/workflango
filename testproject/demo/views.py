from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import (
    CreateView, DeleteView, DetailView, FormView, ListView, TemplateView, UpdateView, View,
)

from workflango.views import ChangeStateView, ObjectHistoryView
from workflango.views_mixins import (
    WorkflowDetailMixin, WorkflowModelCreate, WorkflowModelList, WorkflowModelUpdate,
)

from .filters import RequestFilter, SupplierFilter
from .forms import (
    AttachmentForm, ImpersonateForm, RequestFilterForm, RequestForm, SettingsForm,
    SupplierFilterForm, SupplierForm,
)
from .middleware import IMPERSONATE_SESSION_KEY
from .models import Attachment, Request, Settings, Supplier


class HomeView(LoginRequiredMixin, TemplateView):
    template_name = 'demo/home.html'


# ---------------------------------------------------------------------------
# Impersonation -- admin only. See demo/middleware.py for how request.user
# actually gets swapped for the rest of the request once a session is active.
# ---------------------------------------------------------------------------

class _RealAdminRequiredMixin(UserPassesTestMixin):
    """
    Gates on the *real* logged-in user's superuser status, not request.user --
    while impersonating, request.user is the (non-superuser) impersonated target,
    so checking request.user.is_superuser directly would lock the admin out of
    the very view that lets them stop impersonating.
    """

    def test_func(self):
        real_user = getattr(self.request, 'impersonated_by', None) or self.request.user
        return real_user.is_superuser


class ImpersonateStartView(LoginRequiredMixin, _RealAdminRequiredMixin, FormView):
    template_name = 'demo/impersonate_form.html'
    form_class = ImpersonateForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['real_user'] = getattr(self.request, 'impersonated_by', None) or self.request.user
        return kwargs

    def form_valid(self, form):
        target = form.cleaned_data['user']
        self.request.session[IMPERSONATE_SESSION_KEY] = target.pk
        messages.add_message(self.request, messages.INFO, f'Now impersonating {target}.')
        return redirect('home')


class ImpersonateStopView(LoginRequiredMixin, _RealAdminRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        request.session.pop(IMPERSONATE_SESSION_KEY, None)
        messages.add_message(request, messages.INFO, 'Stopped impersonating.')
        return redirect('home')


# ---------------------------------------------------------------------------
# Supplier
# ---------------------------------------------------------------------------

class SupplierListView(WorkflowModelList, ListView):
    model = Supplier
    template_name = 'demo/supplier_list.html'

    def get_queryset(self):
        qs = super().get_queryset()
        result = SupplierFilter.filter_queryset(self.request, qs)
        self.search_errors = result['search_errors']
        return result['object_list']

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['filter_form'] = SupplierFilterForm(self.request.GET or None)
        context['search_errors'] = self.search_errors
        return context


class SupplierDetailView(WorkflowDetailMixin, DetailView):
    model = Supplier
    template_name = 'demo/supplier_detail.html'


class SupplierCreateView(WorkflowModelCreate, CreateView):
    model = Supplier
    form_class = SupplierForm
    template_name = 'demo/supplier_form.html'

    def get_destination_phase(self):
        return 'proposed'

    def get_destination_owner(self):
        return self.request.user


class SupplierUpdateView(WorkflowModelUpdate, UpdateView):
    model = Supplier
    form_class = SupplierForm
    template_name = 'demo/supplier_form.html'


class SupplierChangeStateView(ChangeStateView):
    model = Supplier

    def get_cancel_url(self):
        return self.get_object().get_absolute_url()


class SupplierHistoryView(ObjectHistoryView):
    model = Supplier


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------

class _RequestObjectNameMixin:
    """
    Every single-object generic view (Detail/Create/Update, and workflango's own
    ChangeStateView/ObjectHistoryView) defaults context_object_name to the
    lowercased model name -- which for this model is literally "request". That
    silently overwrites the real HttpRequest in the template context (normally
    injected by django.template.context_processors.request), breaking every
    `request.user` reference in workflango's shipped templates (workflow_buttons.html,
    form_change_state.html, ...) -- they'd compare against a Request *instance* with
    no .user attribute instead. Naming the extra context alias anything other than
    "request" avoids the collision; nothing here actually reads it; templates use
    "object" throughout, as Django always also provides.
    """
    context_object_name = 'request_obj'


class RequestListView(WorkflowModelList, ListView):
    model = Request
    template_name = 'demo/request_list.html'

    def get_queryset(self):
        qs = super().get_queryset()
        result = RequestFilter.filter_queryset(self.request, qs)
        self.search_errors = result['search_errors']
        return result['object_list']

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['filter_form'] = RequestFilterForm(self.request.GET or None)
        context['search_errors'] = self.search_errors
        return context


class RequestDetailView(_RequestObjectNameMixin, WorkflowDetailMixin, DetailView):
    model = Request
    template_name = 'demo/request_detail.html'


class RequestCreateView(_RequestObjectNameMixin, WorkflowModelCreate, CreateView):
    model = Request
    form_class = RequestForm
    template_name = 'demo/request_form.html'

    def get_destination_phase(self):
        return 'draft'

    def get_destination_owner(self):
        return self.request.user


class RequestUpdateView(_RequestObjectNameMixin, WorkflowModelUpdate, UpdateView):
    model = Request
    form_class = RequestForm
    template_name = 'demo/request_form.html'


class RequestChangeStateView(_RequestObjectNameMixin, ChangeStateView):
    model = Request

    def get_cancel_url(self):
        return self.get_object().get_absolute_url()


class RequestHistoryView(_RequestObjectNameMixin, ObjectHistoryView):
    model = Request


# ---------------------------------------------------------------------------
# Attachment -- plain CRUD tied to a Request, no workflow of its own
# ---------------------------------------------------------------------------

class AttachmentCreateView(LoginRequiredMixin, CreateView):
    model = Attachment
    form_class = AttachmentForm
    template_name = 'demo/attachment_form.html'

    def dispatch(self, request, *args, **kwargs):
        self.request_obj = get_object_or_404(Request, pk=kwargs['request_pk'])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['request_obj'] = self.request_obj
        return context

    def form_valid(self, form):
        form.instance.request = self.request_obj
        return super().form_valid(form)

    def get_success_url(self):
        return self.request_obj.get_absolute_url()


class AttachmentDeleteView(LoginRequiredMixin, DeleteView):
    model = Attachment
    template_name = 'demo/attachment_confirm_delete.html'

    def get_success_url(self):
        return self.object.request.get_absolute_url()


# ---------------------------------------------------------------------------
# Settings -- singleton, superuser only, unrelated to the workflow layer
# ---------------------------------------------------------------------------

class SettingsView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    model = Settings
    form_class = SettingsForm
    template_name = 'demo/settings_form.html'
    success_url = '/settings/'

    def test_func(self):
        return self.request.user.is_superuser

    def get_object(self, queryset=None):
        return Settings.get_solo()
