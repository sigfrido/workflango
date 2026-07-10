try:
    import django_filters
    from collections import OrderedDict
    from django import forms

    _BOOL_CHOICES = (('True', 'Sì'), ('False', 'No'))
    _STATE_CHOICES = (('all', 'Anche passato'), ('past', 'Solo passato'))
    _USER_SHORTCUTS = (('-1', 'Io'), ('-5', 'Non io'), ('-3', 'Nessuno'), ('-4', 'Qualcuno'))

    def _wf_noop(qs, name, value):
        return qs

    class _NoopMultipleChoiceFilter(django_filters.MultipleChoiceFilter):
        """MultipleChoiceFilter that applies no filtering — actual filtering is handled by WorkflowFilterBackend."""
        def filter(self, qs, value):
            return qs

    class WorkflowFilterSetMixin:
        """django-filters FilterSet mixin that adds search_wf_* workflow fields.

        Place before django_filters.FilterSet in the MRO:
            class MyFilter(WorkflowFilterSetMixin, django_filters.FilterSet): ...

        Call self._init_wf_fields(MyModel) in __init__ to populate
        dynamic choices (model phases, active users list).

        Actual filtering is performed by WorkflowFilterBackend; these fields
        exist only for form rendering and query param passthrough.
        """
        declared_filters = OrderedDict([
            ('search_wf_fase', _NoopMultipleChoiceFilter(
                choices=[], label='Fase',
                widget=forms.SelectMultiple(attrs={'class': 'ts-select'}),
            )),
            ('search_wf_messaggio', django_filters.CharFilter(method=_wf_noop, label='Messaggio')),
            ('search_wf_sospeso', django_filters.ChoiceFilter(
                method=_wf_noop, choices=_BOOL_CHOICES, label='Sospeso',
            )),
            ('search_wf_da_leggere', django_filters.ChoiceFilter(
                method=_wf_noop, choices=_BOOL_CHOICES, label='Da leggere',
            )),
            ('search_wf_proprietario', _NoopMultipleChoiceFilter(
                choices=[], label='Proprietario',
                widget=forms.SelectMultiple(attrs={'class': 'ts-select'}),
            )),
            ('search_wf_stato_old', django_filters.ChoiceFilter(
                method=_wf_noop, choices=_STATE_CHOICES, label='Storico',
                empty_label='Corrente',
            )),
        ])

        def _init_wf_fields(self, model):
            from django.contrib.auth import get_user_model
            User = get_user_model()
            self.filters['search_wf_fase'].field.choices = [
                (s, s) for s in model.wfm_config.get_states_list()
            ]
            users = User.objects.filter(is_active=True).order_by('last_name', 'first_name')
            self.filters['search_wf_proprietario'].field.choices = (
                list(_USER_SHORTCUTS)
                + [('', '──────────')]
                + [(str(u.pk), str(u)) for u in users]
            )

except ImportError:
    class WorkflowFilterSetMixin:
        pass
