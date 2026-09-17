from django.db.models import Count, Q

from workflango.filters import WorkflowFilter, boolstr
from workflango.i18n import wgettext_lazy

from .models import Request, Supplier


def filter_by_has_requests(field, value, request):  # noqa: ARG001
    """Supplier custom_query: has at least one related Request, regardless of phase."""
    annotations = {'_request_count': Count('requests')}
    q = Q(_request_count__gt=0) if boolstr(value) else Q(_request_count=0)
    return annotations, q


class SupplierFilter(WorkflowFilter):
    model = Supplier

    search_fields = {
        'search_name': ['company_name'],
        'search_tax_code': ['tax_code'],
        'search_has_requests': {
            'fields': ['requests'],
            'custom_query': filter_by_has_requests,
            'type': 'boolean',
            'description': wgettext_lazy('Has requests'),
        },
    }


class RequestFilter(WorkflowFilter):
    model = Request

    search_fields = {
        'search_budget_min': {
            'fields': ['budget'],
            'operator': '__gte',
            'type': 'decimal',
            'description': wgettext_lazy('Minimum budget'),
        },
        'search_supplier': {
            'fields': ['supplier_id'],
            'type': 'integer',
            'description': wgettext_lazy('Supplier'),
        },
    }
