# -*- coding: utf-8 -*-

from django import forms
from django.forms.widgets import Select

from .filters import USER_CHOICES, STATE_CHOICES, TRUEFALSE_CHOICES

from django.conf import settings

MSG_MAX_LEN = getattr(settings, 'WORKFLOW_TRANS_MSG_MAX_LEN', 4096)

class ChangeStateForm(forms.Form):

    owner = forms.IntegerField(required=False,
        widget=Select()
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
        owner_label = kwargs.pop('owner_label', 'Nuovo proprietario')
        msg_label = kwargs.pop('mesg_label', 'Messaggio')
        opt = 'Obbligatorio'  if require_msg else 'Opzionale'
        msg_placeholder = kwargs.pop('msg_placeholder', f'Messaggio per il destinatario ({opt})')
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
                raise forms.ValidationError(f"Il messaggio è lungo {len(msg)} caratteri, il massimo consentito è {MSG_MAX_LEN}.")
        if self.fields['message'].required and not msg:
            raise forms.ValidationError("Inserire almeno un carattere che non sia lo spazio")
        return msg


    def save(self):
        pass



class WorkflowFilterForm(forms.Form):

    search_proprietario = forms.ChoiceField(
                    label='Proprietario',
                    choices=USER_CHOICES,
                    widget=forms.SelectMultiple(
                        attrs={'class': 'w-100 form-control', 'data-placeholder':'Digitare un nome'}
                    ),
    )

    search_fase =  forms.MultipleChoiceField(
                        label='Fase',
                        widget=forms.SelectMultiple(
                            attrs={'class': 'w-100 form-control', 'data-placeholder':'Digitare una fase'}
                        ),
                      )

    search_messaggio =  forms.CharField(
                        label='Messaggio',
                        widget=forms.TextInput(attrs={'placeholder': 'Testo contenuto nel messaggio', 'class': 'form-control'}),
                        help_text='Ricerca testo avanzata: adozione or firma'
                      )

    search_sospeso = forms.NullBooleanField(
                        label='Sospeso',
                        widget=Select(
                            attrs={'class':'form-select'},
                            choices=TRUEFALSE_CHOICES,
                        )
                    )


    search_da_leggere = forms.NullBooleanField(
                        label='Leggere',
                        widget=Select(
                            attrs={'class':'form-select'},
                            choices=TRUEFALSE_CHOICES,
                        )
                    )


    search_stato_old =  forms.ChoiceField(
                        label='Storico',
                        choices = STATE_CHOICES,
                        widget=forms.Select(
                            attrs={'class':'form-select'}
                        ),
                      )

    # TODO spostare in dashborad.forms_mixins
    search_following = forms.NullBooleanField(
                        label='Seguo',
                        widget=Select(
                            attrs={'class':'form-select'},
                            choices=TRUEFALSE_CHOICES,
                        ),
    )


    search_data_min = forms.DateField(
                    label='Data min',
                    input_formats=['%Y-%m-%d', '%d/%m/%Y'],
                    widget=forms.DateInput(
                        attrs={'class':'form-control fs-12', 'type': 'date'},
                        format='%d/%m/%Y'
                    ),
                    help_text='Data minima di ingresso nella fase corrente o nelle fasi selezionate'
    )


    search_data_max = forms.DateField(
                    label='Data max',
                    input_formats=['%Y-%m-%d', '%d/%m/%Y'],
                    widget=forms.DateInput(
                        attrs={'class':'form-control fs-12', 'type': 'date'},
                        format='%d/%m/%Y'
                    ),
                    help_text='Data massima di ingresso nella fase corrente o nelle fasi selezionate'
    )




    def __init__(self, *args, **kwargs):
        super(WorkflowFilterForm, self).__init__(*args, **kwargs)
        self.fields['search_fase'].widget.choices = self.get_state_choices()


    def get_state_choices(self):
        state_choices = [(x, x) for x in self.model.wfm_config.get_states_list()]
        return state_choices


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
