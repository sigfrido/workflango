# -*- coding: utf-8 -*-

from django import forms
from django.forms.widgets import Select

from .filters import USER_CHOICES, STATE_CHOICES, TRUEFALSE_CHOICES, get_custom_owner_filters
from .i18n import wgettext, wgettext_lazy

from django.conf import settings

MSG_MAX_LEN = getattr(settings, 'WF_TRANS_MSG_MAX_LEN', 4096)

class ChangeStateForm(forms.Form):

    owner = forms.IntegerField(required=False,
        widget=Select(attrs={'class': 'form-select'})
    )

    message = forms.CharField(required=False,
        widget=forms.Textarea(attrs={'rows': 4, 'class': 'form-control'})
    )

    def __init__(self, *args, **kwargs):

        kwargs['initial'] = kwargs.get('initial', {})

        instance = kwargs.pop('instance', False)
        require_owner = kwargs.pop('require_owner', False)
        default_owner = kwargs.pop('default_owner', None)
        require_msg = kwargs.pop('require_msg', require_owner)
        owner_choices = kwargs.pop('owner_choices', {})
        owner_label = kwargs.pop('owner_label', wgettext('New owner'))
        msg_label = kwargs.pop('mesg_label', wgettext('Message'))
        opt = wgettext('Required') if require_msg else wgettext('Optional')
        msg_placeholder = kwargs.pop('msg_placeholder', wgettext('Message for the recipient (%(opt)s)') % {'opt': opt})
        if default_owner:
            kwargs['initial']['owner'] = default_owner.id
        super(ChangeStateForm, self).__init__(*args, **kwargs)

        self.fields['message'].required = require_msg
        self.fields['message'].label = msg_label
        self.fields['message'].widget.attrs['placeholder'] = msg_placeholder

        self.fields['owner'].required = require_owner
        self.fields['owner'].widget.choices = owner_choices
        self.fields['owner'].label = owner_label


    def clean_message(self):
        msg = self.cleaned_data['message']
        if msg:
            msg = msg.strip()
            if len(msg) > MSG_MAX_LEN:
                raise forms.ValidationError(
                    wgettext("The message is %(len)s characters long, the maximum allowed is %(max)s.") % {
                        'len': len(msg), 'max': MSG_MAX_LEN,
                    }
                )
        if self.fields['message'].required and not msg:
            raise forms.ValidationError(wgettext("Enter at least one non-space character"))
        return msg


    def save(self):
        pass



class WorkflowFilterForm(forms.Form):
    """
    Every field is `required=False`: this is a search/filter form, not a data-entry
    form -- an unfilled field must mean "don't filter on this", not "please pick
    something before submitting". Concretely: search_wf_history's first choice is
    `('', 'Current')` (an empty *value*, not an empty *selection*); with the field
    left at Django's default `required=True`, the browser's HTML5 validation refuses
    to submit an empty-valued selection at all, blocking the form even though a
    perfectly meaningful choice ("Current") is already selected. Same issue on every
    other field here (blank Select/date/text left untouched by the user). Leaving
    search_wf_owner/search_wf_phase blank means "no filter", which is a
    distinct, still-selectable choice from explicitly picking e.g. owner "None"
    (`none` in USER_CHOICES, meaning "owner is null") -- required=False doesn't change
    that distinction, it only stops the browser from forcing a choice.
    """

    search_wf_owner = forms.ChoiceField(
                    label=wgettext_lazy('Owner'),
                    choices=USER_CHOICES,
                    required=False,
                    widget=forms.SelectMultiple(
                        attrs={'class': 'w-100 form-control', 'data-placeholder': wgettext_lazy('Type a name')}
                    ),
    )

    search_wf_phase =  forms.MultipleChoiceField(
                        label=wgettext_lazy('Phase'),
                        required=False,
                        widget=forms.SelectMultiple(
                            attrs={'class': 'w-100 form-control', 'data-placeholder': wgettext_lazy('Type a phase')}
                        ),
                      )

    search_wf_message =  forms.CharField(
                        label=wgettext_lazy('Message'),
                        required=False,
                        widget=forms.TextInput(attrs={'placeholder': wgettext_lazy('Text contained in the message'), 'class': 'form-control'}),
                        help_text=wgettext_lazy('Advanced text search: adoption or signature')
                      )

    search_wf_suspended = forms.NullBooleanField(
                        label=wgettext_lazy('Suspended'),
                        required=False,
                        widget=Select(
                            attrs={'class':'form-select'},
                            choices=TRUEFALSE_CHOICES,
                        )
                    )


    search_wf_unread = forms.NullBooleanField(
                        label=wgettext_lazy('Unread'),
                        required=False,
                        widget=Select(
                            attrs={'class':'form-select'},
                            choices=TRUEFALSE_CHOICES,
                        )
                    )


    search_wf_history =  forms.ChoiceField(
                        label=wgettext_lazy('History'),
                        choices = STATE_CHOICES,
                        required=False,
                        widget=forms.Select(
                            attrs={'class':'form-select'}
                        ),
                      )

    # TODO spostare in dashborad.forms_mixins
    search_following = forms.NullBooleanField(
                        label=wgettext_lazy('Following'),
                        required=False,
                        widget=Select(
                            attrs={'class':'form-select'},
                            choices=TRUEFALSE_CHOICES,
                        ),
    )


    search_wf_date_min = forms.DateField(
                    label=wgettext_lazy('Min date'),
                    required=False,
                    widget=forms.DateInput(
                        attrs={'class':'form-control fs-12', 'type': 'date'},
                        format='%Y-%m-%d'  # HTML5 date input: browser requires ISO regardless of locale
                    ),
                    help_text=wgettext_lazy('Minimum entry date into the current phase or the selected phases')
    )


    search_wf_date_max = forms.DateField(
                    label=wgettext_lazy('Max date'),
                    required=False,
                    widget=forms.DateInput(
                        attrs={'class':'form-control fs-12', 'type': 'date'},
                        format='%Y-%m-%d'  # HTML5 date input: browser requires ISO regardless of locale
                    ),
                    help_text=wgettext_lazy('Maximum entry date into the current phase or the selected phases')
    )




    def __init__(self, *args, **kwargs):
        super(WorkflowFilterForm, self).__init__(*args, **kwargs)
        self.fields['search_wf_phase'].widget.choices = self.get_state_choices()
        self.fields['search_wf_owner'].widget.choices = self.get_owner_choices()


    def get_state_choices(self):
        state_choices = [(x, x) for x in self.model.wfm_config.get_states_list()]
        return state_choices


    def get_owner_choices(self):
        return USER_CHOICES + tuple((key, label) for key, (label, _fn) in get_custom_owner_filters().items())


class SearchListForm(forms.Form):
    """
    Base form for list views that filter by owner.

    Pass user_choices to __init__ to populate the owner dropdown with
    user-specific choices in addition to the generic USER_CHOICES.
    """

    field_search_proprietario = 'search_proprietario'

    def __init__(self, *args, **kwargs):
        user_choices = kwargs.pop('user_choices', None)
        super().__init__(*args, **kwargs)
        if user_choices:
            self.fields[self.field_search_proprietario].widget.choices = USER_CHOICES + user_choices
