from django.core.exceptions import ValidationError
from django.db import models

from workflango.models import WorkflowModel

_TAX_CODE_ERROR = 'Tax code must be 5 to 20 alphanumeric characters (letters, digits, dashes).'


def _is_valid_tax_code(value: str) -> bool:
    stripped = value.replace('-', '')
    return 5 <= len(value) <= 20 and stripped.isalnum()


class Supplier(WorkflowModel):
    """
    Workflow: proposed -> active -> archived.

    Anyone creates a supplier as 'proposed' (and becomes its owner). Only a
    manager can move it to 'active' or on to 'archived' -- enforced via
    'allowed_groups' on the transition itself. Since a phase-changing
    transition also requires the acting user to be the *current owner*
    (see workflango.models.InstanceWorkflowManager.transition_allowed), a
    manager who isn't already the owner takes ownership first (the 'admin'
    bucket below grants that) and then performs the transition.
    """

    company_name = models.CharField(max_length=200)
    tax_code = models.CharField(max_length=20, blank=True)
    certification = models.FileField(upload_to='suppliers/certifications/', null=True, blank=True)

    class Meta:
        verbose_name = 'Supplier'
        verbose_name_plural = 'Suppliers'
        ordering = ['company_name']

    def __str__(self):
        return f"{self.pk} - {self.company_name}"

    def clean(self):
        if self.tax_code and not _is_valid_tax_code(self.tax_code):
            raise ValidationError({'tax_code': _TAX_CODE_ERROR})

    workflow_defaults = {
        # Everyone can see any supplier regardless of phase; edit/admin (who can
        # transition it) is narrowed per phase below.
        'read': ['USERS', 'MANAGERS'], 'edit': [], 'admin': [],
        'properties': {'edit_button_label': 'Edit'},
    }

    # 'editable_fields' below is a custom properties key, read only by SupplierForm
    # (see forms.py) -- workflango itself doesn't know about it, same as any other
    # app-specific key under 'properties' (see docs/wf-configuration.md, section 3).
    workflow_phases = (
        (None, {
            'reachable_phases': {'proposed': {}},
            'edit': ['USERS', 'MANAGERS'],
            'properties': {'editable_fields': {'company_name', 'tax_code', 'certification'}},
        }),
        ('proposed', {
            'reachable_phases': {
                'active': {'allowed_groups': ['MANAGERS'], 'caption': 'Activate'},
            },
            'edit': ['USERS', 'MANAGERS'],
            'admin': ['MANAGERS'],
            'properties': {'editable_fields': {'company_name', 'tax_code', 'certification'}},
        }),
        ('active', {
            'reachable_phases': {
                'archived': {'allowed_groups': ['MANAGERS'], 'caption': 'Archive'},
            },
            'edit': ['MANAGERS'],
            'admin': ['MANAGERS'],
            'properties': {'editable_fields': {'certification'}},
        }),
        ('archived', {
            'is_closed': True,
            'reachable_phases': {},
            'edit': [],
            'properties': {'editable_fields': set()},
        }),
    )


class Request(WorkflowModel):
    """
    Workflow: draft -> submitted -> approved / rejected.

    A request can only target an active Supplier -- enforced both in
    RequestForm (dropdown scoped to active suppliers) and here in clean()
    as an integrity net (full_clean() runs on every ModelForm save and
    inside wfm.transition()).
    """

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    budget = models.DecimalField(max_digits=12, decimal_places=2)
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name='requests',
    )
    manager_notes = models.TextField(blank=True)
    reference_code = models.CharField(max_length=20, blank=True)
    justification = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Request'
        verbose_name_plural = 'Requests'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.pk} - {self.title}"

    def clean(self):
        if self.supplier_id and self.supplier.current_state and self.supplier.current_state.phase != 'active':
            raise ValidationError({'supplier': 'Requests can only target an active supplier.'})

    workflow_defaults = {
        # Everyone can see any request regardless of phase; edit/admin (who can
        # transition it) is narrowed per phase below.
        'read': ['USERS', 'MANAGERS'], 'edit': [], 'admin': [],
        'properties': {'edit_button_label': 'Edit'},
    }

    # 'editable_fields' below is a custom properties key, read only by RequestForm
    # (see forms.py) -- workflango itself doesn't know about it, same as any other
    # app-specific key under 'properties' (see docs/wf-configuration.md, section 3).
    workflow_phases = (
        (None, {
            'reachable_phases': {'draft': {}},
            'edit': ['USERS', 'MANAGERS'],
            'properties': {'editable_fields': {'title', 'description', 'budget', 'supplier'}},
        }),
        ('draft', {
            'reachable_phases': {
                'submitted': {'caption': 'Submit'},
            },
            'edit': ['USERS', 'MANAGERS'],
            'admin': ['MANAGERS'],
            'properties': {'editable_fields': {'title', 'description', 'budget', 'supplier'}},
        }),
        ('submitted', {
            'reachable_phases': {
                'approved': {'allowed_groups': ['MANAGERS'], 'caption': 'Approve'},
                'rejected': {'allowed_groups': ['MANAGERS'], 'caption': 'Reject'},
            },
            'edit': [],
            'admin': ['MANAGERS'],
            'properties': {'editable_fields': {'manager_notes', 'reference_code'}},
        }),
        ('approved', {
            'is_closed': True,
            'reachable_phases': {},
            'edit': [],
            'properties': {'editable_fields': set()},
        }),
        ('rejected', {
            'is_closed': True,
            'reachable_phases': {},
            'edit': [],
            'properties': {'editable_fields': set()},
        }),
    )


class Attachment(models.Model):
    request = models.ForeignKey(Request, on_delete=models.CASCADE, related_name='attachments')
    description = models.CharField(max_length=255)
    file = models.FileField(upload_to='attachments/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Attachment'
        verbose_name_plural = 'Attachments'
        ordering = ['uploaded_at']

    def __str__(self):
        return f"{self.pk} - {self.description}"


class Settings(models.Model):
    """Singleton settings row -- see demo/views.py:SettingsView."""

    auto_approval_threshold = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text='Requests with a budget below this amount could be auto-approved.',
    )
    notification_email = models.EmailField(blank=True)

    class Meta:
        verbose_name = 'Settings'

    def __str__(self):
        return 'Settings'

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


Supplier.configure_workflow()
Request.configure_workflow()
