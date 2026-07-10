# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import copy
import datetime

from django.db.models import Q, F
from django.utils.html import escape

from .exceptions import get_exception_error_msg


# ---------------------------------------------------------------------------
# Filter utilities (moved from compat.py)
# ---------------------------------------------------------------------------

class FilterException(ValueError):
    pass


TRUEFALSE_CHOICES = (
    ('', ''),
    (True, 'Si'),
    (False, 'No'),
)


def boolstr(strval):
    v = str(strval).lower()
    if v in ('1', 't', 'true', 'v', 'vero', 'y', 'yes', 'si'):
        return True
    if v in ('0', 'f', 'false', 'falso', 'n', 'no'):
        return False
    raise FilterException(f'Valore booleano non valido ({escape(strval)}): ammessi 1/0, t(rue)/f(alse), s(i)/(n)o, y(es)/n(o)')


def datestr_local2iso(date_str):
    for fmt in ['%d/%m/%Y', '%d/%m/%y']:
        try:
            dt = datetime.datetime.strptime(date_str, fmt)
            return dt.strftime('%Y-%m-%d')
        except Exception:
            pass
    return date_str


def text_search(model_fields, request_field_value, _request=None):
    if not request_field_value:
        return Q()
    terms = request_field_value.split()
    q = Q()
    for term in terms:
        term_q = Q()
        for field in model_fields:
            term_q |= Q(**{field + '__icontains': term})
        q &= term_q
    return q


class BaseFilter:
    """
    Class-based queryset filter driven by a declarative search_fields dict.

    Subclass this and define search_fields to describe which request parameters
    map to which model fields and how they should be filtered.

    Compatible with both Django template views (request.GET) and DRF views
    (request.query_params, which supports .getlist() like Django's QueryDict).
    For DRF integration use WorkflowFilterBackend instead of calling
    filter_queryset() directly.
    """
    search_fields = {}
    apply_distinct = True
    order_field = 'query_order'
    allowed_orderings = []
    max_num_orderings = 0
    default_order_by = ['pk']

    @classmethod
    def filter_queryset(cls, request, queryset):
        result = {
            'search_errors': [],
            'filtering': False,
            'order_by_fields': [],
            'object_list': None,
        }
        try:
            annotations, search_query = cls.build_query(cls.get_search_fields(), request.GET, request)
            if search_query:
                result['filtering'] = True
                if annotations:
                    queryset = queryset.annotate(**annotations)
                queryset = queryset.filter(search_query)
            if cls.order_field and cls.order_field in request.GET and request.GET[cls.order_field]:
                order_by_fields = [
                    x for x in request.GET[cls.order_field].split(',')
                    if x.replace('-', '') in [f for f, _ in cls.allowed_orderings]
                ]
                order_by_Fs = map(
                    lambda fn: F(fn[1:]).desc(nulls_last=True) if fn[0] == '-' else F(fn).asc(nulls_last=True),
                    order_by_fields
                )
                queryset = queryset.order_by(*order_by_Fs)
                result['order_by_fields'] = order_by_fields
            elif cls.default_order_by:
                queryset = queryset.order_by(*cls.default_order_by)
            if cls.apply_distinct:
                queryset = queryset.distinct()
            result['object_list'] = queryset
        except Exception as e:
            result['search_errors'].append(get_exception_error_msg(e))
            result['object_list'] = queryset.none()
        return result

    @classmethod
    def get_search_fields(cls):
        sfdict = {}
        for klass in tuple(cls.__bases__) + (cls,):
            if hasattr(klass, 'search_fields'):
                sfdict.update(copy.deepcopy(klass.search_fields))
        cls.post_process_search_fields(sfdict)
        return sfdict

    @classmethod
    def post_process_search_fields(cls, sfdict):
        pass

    @classmethod
    def build_query(cls, fields_dict, params_dict, request=None):
        and_query = Q()
        annotations = {}
        for fieldname, search_field in fields_dict.items():
            field_q_value = params_dict.get(fieldname, None)
            if field_q_value and hasattr(field_q_value, 'strip'):
                field_q_value = field_q_value.strip()
            if field_q_value not in (None, ''):
                or_query = None
                if isinstance(search_field, list):
                    field_list = search_field
                    search_operator = '__icontains'
                    fixed_filters = None
                    multiple_values = False
                    custom_query_method = None
                    value_mapper = None
                else:
                    if search_field.get('ignore', False):
                        continue
                    field_list = search_field['fields']
                    search_operator = search_field.get('operator', '')
                    fixed_filters = search_field.get('fixed_filters', None)
                    multiple_values = search_field.get('multiple', False)
                    custom_query_method = search_field.get('custom_query', None)
                    value_mapper = search_field.get('value_mapper', None)
                    filter_annotations = search_field.get('annotations', {})
                    if filter_annotations:
                        annotations.update(filter_annotations)
                for model_field in field_list:
                    try:
                        if multiple_values:
                            if hasattr(params_dict, 'getlist'):
                                request_field_value = params_dict.getlist(fieldname)
                            elif type(field_q_value) == list:
                                request_field_value = field_q_value
                            else:
                                request_field_value = [field_q_value]
                            if value_mapper:
                                request_field_value = [value_mapper(v) for v in request_field_value]
                        else:
                            request_field_value = field_q_value if not value_mapper else value_mapper(field_q_value)
                        if custom_query_method:
                            custom_result = custom_query_method(model_field, request_field_value, request if request else params_dict)
                            if isinstance(custom_result, tuple):
                                custom_annotations, cf = custom_result
                                annotations.update(custom_annotations)
                            else:
                                cf = custom_result
                            or_query = or_query | cf if or_query else cf
                        else:
                            filter_dict = {model_field + search_operator: request_field_value}
                            or_query = or_query | Q(**filter_dict) if or_query else Q(**filter_dict)
                    except Exception as e:
                        raise FilterException(f'Errore nel filtro per il campo {model_field}: {escape(get_exception_error_msg(e))}')
                fixed_filters_q = Q()
                if fixed_filters:
                    if callable(fixed_filters):
                        fixed_filters_q = fixed_filters(params_dict)
                    elif type(fixed_filters) is dict:
                        fixed_filters_q = Q(**fixed_filters)
                and_query = and_query & or_query & fixed_filters_q
        return annotations, and_query


# ---------------------------------------------------------------------------
# Workflow-specific filter choices
# ---------------------------------------------------------------------------

USER_CHOICES = (
    ('', ''),
    ('-1', 'Io'),            # in [user.id]
    ('-2', 'Io o nessuno'),  # in [null, user.id]
    ('-3', 'Nessuno'),       # is null
    ('-4', 'Qualcuno'),      # is not null
    ('-5', 'Non io'),        # not in [user.id]
    ('-6', 'Non attivo'),    # owner__is_active=False
    ('-7', 'Assente'),       # owner__user_config__away=True
)

STATE_CHOICES = (
    ('', 'Corrente'),
    ('all', 'Anche passato'),
    ('past', 'Solo passato'),
)


def filter_by_owner(field, owners, request):
    status, lookup = _get_status_lookup(request)
    q = None
    for owner_id in owners:
        if owner_id == '-1':
            req = build_Q(lookup, 'owner', request.user)
        elif owner_id == '-2':
            req = build_Q(lookup, 'owner', request.user) | build_Q(lookup, 'owner', None)
        elif owner_id == '-3':
            req = build_Q(lookup, 'owner', None)
        elif owner_id == '-4':
            req = build_Q(lookup, 'owner__isnull', False)
        elif owner_id == '-5':
            req = ~build_Q(lookup, 'owner', request.user) & build_Q(lookup, 'owner__isnull', False)
        elif owner_id == '-6':
            req = build_Q(lookup, 'owner__is_active', False)
        elif owner_id == '-7':
            req = build_Q(lookup, 'owner__user_config__away', True)
        else:
            req = build_Q(lookup, 'owner__id', owner_id)
        q = q | req if q else req
    return _fixed_filter(q, status)


def filter_by_state(field, states, request):
    status, lookup = _get_status_lookup(request)
    req = build_Q(lookup, 'phase__in', states)
    return _fixed_filter(req, status)


def filter_by_suspended(field, suspended, request):
    status, lookup = _get_status_lookup(request)
    req = build_Q(lookup, 'suspended', boolstr(suspended))
    return _fixed_filter(req, status)


def filter_by_unread(field, unread, request):
    status, lookup = _get_status_lookup(request)
    req = build_Q(lookup, 'unread', boolstr(unread))
    return _fixed_filter(req, status)


def filter_by_message(field, message, request):
    status, lookup = _get_status_lookup(request)
    req = text_search((f'{lookup}__message', ), message, request)
    return _fixed_filter(req, status)


def filter_by_date_min(field, date, request):
    status, lookup = _get_status_lookup(request)
    req = build_Q(lookup, 'state_date__gte', date + ' 00:00')
    return _fixed_filter(req, status)


def filter_by_date_max(field, date, request):
    status, lookup = _get_status_lookup(request)
    req = build_Q(lookup, 'state_date__lte', date + ' 23:59')
    return _fixed_filter(req, status)


def build_Q(lookup, field, value):
    key = f'{lookup}__{field}'
    d = {key: value}
    return Q(**d)


def _get_status_lookup(request):
    status = request.GET.get('search_wf_stato_old', '')
    if status == '':
        lookup = 'wfm_state'
    else:
        lookup = 'states'
    return (status, lookup)


def _fixed_filter(qobj, status):
    if status == 'past':
        return qobj & Q(states__next_state__isnull=False)
    else:
        return qobj


# ---------------------------------------------------------------------------
# WorkflowFilter — Django template view filter
# ---------------------------------------------------------------------------

class WorkflowFilter(BaseFilter):
    """
    BaseFilter subclass with predefined search fields for workflow state, owner,
    suspension, unread flag, message text, and date range.

    Usage in a Django template list view::

        result = WorkflowFilter.filter_queryset(request, MyModel.objects.all())
        object_list = result['object_list']

    For DRF views use WorkflowFilterBackend instead.
    """

    model = None

    search_fields = {
        'search_wf_fase': {
            'custom_query': filter_by_state,
            'multiple': True,
            'fields': ['states__phase'],
            'description': 'Fase del workflow',
            'type': 'string',
        },
        'search_wf_messaggio': {
            'fields': ['states__message'],
            'custom_query': filter_by_message,
            'description': 'Messaggio di transizione workflow',
            'type': 'string',
            'advanced_text_search': True,
        },
        'search_wf_sospeso': {
            'custom_query': filter_by_suspended,
            'fields': ['states__suspended'],
            'description': 'Il workflow è in stato sospeso',
            'type': 'boolean',
        },
        'search_wf_da_leggere': {
            'custom_query': filter_by_unread,
            'fields': ['states__unread'],
            'description': "Il record non è ancora stato letto dall'assegnatario",
            'type': 'boolean',
        },
        'search_wf_proprietario': {
            'fields': ['states__owner_id'],
            'custom_query': filter_by_owner,
            'multiple': True,
            'description': 'Proprietario del record',
            'type': 'integer',
            'choices': USER_CHOICES + (('id', 'Codice utente'), ),
        },
        'search_wf_data_min': {
            'fields': ['states__state_date'],
            'custom_query': filter_by_date_min,
            'description': 'Data minima di ingresso nella fase',
            'type': 'date',
            'value_mapper': datestr_local2iso,
        },
        'search_wf_data_max': {
            'fields': ['states__state_date'],
            'custom_query': filter_by_date_max,
            'description': 'Data massima di ingresso nella fase',
            'type': 'date',
            'value_mapper': datestr_local2iso,
        },
        'search_wf_stato_old': {
            'ignore': True,
            'description': 'Ricerca negli stati passati',
            'type': 'string',
            'choices': STATE_CHOICES,
        },
    }

    @classmethod
    def post_process_search_fields(cls, sfdict):
        if hasattr(cls, 'model') and hasattr(cls.model, 'wfm_config') and 'search_fase' in sfdict:
            sfdict['search_fase']['choices'] = cls.model.wfm_config.get_states_list()


# ---------------------------------------------------------------------------
# WorkflowFilterBackend — DRF integration
# ---------------------------------------------------------------------------

try:
    from rest_framework.filters import BaseFilterBackend

    class WorkflowFilterBackend(BaseFilterBackend):
        """
        DRF filter backend wrapping WorkflowFilter.

        Reads the same query parameters as WorkflowFilter (search_fase,
        search_proprietario, search_sospeso, etc.) from request.query_params.

        Usage::

            class MyModelViewSet(ModelViewSet):
                filter_backends = [WorkflowFilterBackend]
        """
        workflow_filter_class = WorkflowFilter

        def filter_queryset(self, request, queryset, view):
            # DRF request.query_params is a QueryDict, compatible with .get()/.getlist()
            # BaseFilter.filter_queryset expects request.GET — adapt via a proxy
            _request = _DRFRequestProxy(request)
            result = self.workflow_filter_class.filter_queryset(_request, queryset)
            return result['object_list']

    class _DRFRequestProxy:
        """Minimal proxy so BaseFilter can call request.GET on a DRF request."""
        def __init__(self, drf_request):
            self.GET = drf_request.query_params
            self.user = drf_request.user

except ImportError:
    pass  # DRF not installed; WorkflowFilterBackend not available
