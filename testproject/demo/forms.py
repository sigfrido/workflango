from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm

from workflango.filters import TRUEFALSE_CHOICES
from workflango.forms import WorkflowFilterForm

from .models import Attachment, Request, Settings, Supplier


def _bootstrapify(form):
    """
    Adds Bootstrap's block-level, full-width classes to every field's widget.

    Django's default widget rendering carries no CSS classes at all, so a plain
    `<input>`/`<select>` is inline-block at browser-default width -- it doesn't line up
    left-aligned under a `form-label` above it the way `form-control`/`form-select` do
    (both `display: block; width: 100%`). Call this once from every form's __init__.
    """
    for field in form.fields.values():
        widget = field.widget
        css_class = 'form-check-input' if isinstance(widget, forms.CheckboxInput) else (
            'form-select' if isinstance(widget, (forms.Select, forms.SelectMultiple)) else 'form-control'
        )
        existing = widget.attrs.get('class', '')
        widget.attrs['class'] = f'{existing} {css_class}'.strip()


class LoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrapify(self)


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ['company_name', 'tax_code', 'certification']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrapify(self)
        phase = self.instance.current_state.phase if self.instance.pk and self.instance.current_state else None
        self.editable_fields = Supplier.wfm_config.get_phase_config(phase)['properties'].get('editable_fields', set())
        for name in self.fields:
            if name not in self.editable_fields:
                self.fields[name].required = False
                self.fields[name].disabled = True


class RequestForm(forms.ModelForm):
    class Meta:
        model = Request
        fields = ['title', 'description', 'budget', 'supplier', 'manager_notes', 'reference_code']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrapify(self)
        # A request may only target an active supplier -- see Request.clean() for the
        # integrity-net check that catches this even if the queryset restriction here
        # is bypassed (e.g. a supplier that was active when the form was rendered but
        # got archived before submit).
        self.fields['supplier'].queryset = Supplier.objects.filter(wfm_state__phase='active')
        phase = self.instance.current_state.phase if self.instance.pk and self.instance.current_state else None
        self.editable_fields = Request.wfm_config.get_phase_config(phase)['properties'].get('editable_fields', set())
        for name in self.fields:
            if name not in self.editable_fields:
                self.fields[name].required = False
                self.fields[name].disabled = True


class AttachmentForm(forms.ModelForm):
    class Meta:
        model = Attachment
        fields = ['description', 'file']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrapify(self)


class SettingsForm(forms.ModelForm):
    class Meta:
        model = Settings
        fields = ['auto_approval_threshold', 'notification_email']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrapify(self)


class SupplierFilterForm(WorkflowFilterForm):
    model = Supplier

    search_name = forms.CharField(
        label='Name', required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Company name'}),
    )
    search_tax_code = forms.CharField(
        label='Tax code', required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Tax code'}),
    )
    search_has_requests = forms.NullBooleanField(
        label='Has requests', required=False,
        widget=forms.Select(choices=TRUEFALSE_CHOICES),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrapify(self)


class RequestFilterForm(WorkflowFilterForm):
    model = Request

    search_budget_min = forms.DecimalField(
        label='Minimum budget', required=False,
        widget=forms.NumberInput(attrs={'step': '0.01'}),
    )
    search_supplier = forms.ModelChoiceField(
        # Unlike RequestForm's create/edit dropdown, not scoped to active suppliers --
        # a historical request may target a supplier that's since been archived, and
        # filtering is a read-only, broader-scope operation.
        queryset=Supplier.objects.all(), label='Supplier', required=False, empty_label='---',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrapify(self)


class ImpersonateForm(forms.Form):
    user = forms.ModelChoiceField(
        queryset=get_user_model().objects.none(),
        label='User to impersonate',
        empty_label='---',
    )

    def __init__(self, *args, real_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrapify(self)
        qs = get_user_model().objects.filter(is_active=True, is_superuser=False)
        if real_user is not None:
            qs = qs.exclude(pk=real_user.pk)
        self.fields['user'].queryset = qs.order_by('username')
