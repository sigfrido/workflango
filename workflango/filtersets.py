try:
    import django_filters
    from collections import OrderedDict
    from django import forms

    from .filters import get_custom_owner_filters
    from .i18n import wgettext_lazy

    _BOOL_CHOICES = (('True', wgettext_lazy('Yes')), ('False', wgettext_lazy('No')))
    _STATE_CHOICES = (('all', wgettext_lazy('Also past')), ('past', wgettext_lazy('Only past')))
    _USER_SHORTCUTS = (
        ('me', wgettext_lazy('Me')), ('not_me', wgettext_lazy('Not me')),
        ('none', wgettext_lazy('None')), ('someone', wgettext_lazy('Someone')),
    )

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
            ('search_wf_phase', _NoopMultipleChoiceFilter(
                choices=[], label=wgettext_lazy('Phase'),
                widget=forms.SelectMultiple(attrs={'class': 'ts-select'}),
            )),
            ('search_wf_message', django_filters.CharFilter(method=_wf_noop, label=wgettext_lazy('Message'))),
            ('search_wf_suspended', django_filters.ChoiceFilter(
                method=_wf_noop, choices=_BOOL_CHOICES, label=wgettext_lazy('Suspended'),
            )),
            ('search_wf_unread', django_filters.ChoiceFilter(
                method=_wf_noop, choices=_BOOL_CHOICES, label=wgettext_lazy('Unread'),
            )),
            ('search_wf_owner', _NoopMultipleChoiceFilter(
                choices=[], label=wgettext_lazy('Owner'),
                widget=forms.SelectMultiple(attrs={'class': 'ts-select'}),
            )),
            ('search_wf_history', django_filters.ChoiceFilter(
                method=_wf_noop, choices=_STATE_CHOICES, label=wgettext_lazy('History'),
                empty_label=wgettext_lazy('Current'),
            )),
        ])

        def _init_wf_fields(self, model):
            from django.contrib.auth import get_user_model
            User = get_user_model()
            self.filters['search_wf_phase'].field.choices = [
                (s, s) for s in model.wfm_config.get_phases_list()
            ]
            users = User.objects.filter(is_active=True).order_by('last_name', 'first_name')
            custom_shortcuts = [(key, label) for key, (label, _fn) in get_custom_owner_filters().items()]
            self.filters['search_wf_owner'].field.choices = (
                list(_USER_SHORTCUTS)
                + custom_shortcuts
                + [('', '──────────')]
                + [(str(u.pk), str(u)) for u in users]
            )

except ImportError:
    class WorkflowFilterSetMixin:
        pass
