# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.views.generic.edit import UpdateView
from django.views.generic.detail import DetailView

from django.contrib.auth.models import User
from django.http import HttpResponseRedirect

from .views_mixins import WorkflowModelChangeState, AccessDeniedMixin, CachedGetObjectMixin

from .forms import ChangeStateForm


class ChangeStateView(CachedGetObjectMixin, WorkflowModelChangeState, UpdateView):
    """
    Generic WF change state view
    """
    model = None
    form_class = ChangeStateForm
    template_name = "workflow/form_change_state.html"
    transition = None
    cancel_url = '/'

    command_captions = {
        # 'command' : ('title', 'message', 'button_caption'),
        'take-ownership' : ('Prendi in carico', 'L\'oggetto verrà preso in carico.', 'Prendi in carico'),
        'release' : ('Rilascia', 'L\'oggetto  verrà rilasciato e tornerà disponibile per la presa in carico.', 'Rilascia' ),
        'reject' : ('Respingi a stato precedente', 'L\'oggetto verrà respinto alla fase e all\'utente precedente che te l\'ha assegnato', 'Respingi'),
        'delegate' : ('Delega', 'L\'oggetto verrà delegato all\'utente selezionato.', 'Delega'),
        'assign' : ('Assegna', 'L\'oggetto verrà assegnato all\'utente selezionato.', 'Assegna'),
        'suspend' : ('Sospendi', 'L\'oggetto verrà sospeso.', 'Sospendi'),
        'resume' : ('Riprendi', 'L\'oggetto verrà ripreso.', 'Riprendi'),
    }

    def get(self, request, *args, **kwargs):
        if not self.check_transition_is_valid():
            return HttpResponseRedirect(self.get_cancel_url())
        self.before_draw()
        return super(ChangeStateView, self).get(request, *args, **kwargs)
    
    
    def before_draw(self):
        """
        Questo handler viene chiamato da get() quando le validazioni sono positive, 
        e consente ad esempio di aggiungere un messaggio prima della conferma del passaggio di stato
        """
        pass


    def get_cancel_url(self):
        return self.cancel_url


    def get_transition(self):
        if not self.transition:
            obj = self.get_object()
            self.transition = obj.wfm.get_transition(self.destination_state, self.request.user)
        return self.transition


    def get_transition_gui_message(self, transition):
        return f"Confermare il passaggio alla fase: {transition.destination}"


    def get_context_data(self, *args, **kwargs):
        context = super(ChangeStateView, self).get_context_data(*args, **kwargs)
        context = self.get_workflow_context(context)
        transition = self.get_transition()
        context['transition'] = transition
        context['last_owner'] = transition.get_last_owner()
        if transition.command:
            context['title'], context['message'], context['button_caption'] = self.command_captions[self.destination_state]
        else:
            context['title'] = 'Passaggio a fase: '  + transition.destination
            context['message'] = self.get_transition_gui_message(transition)
            context['button_caption'] = transition.caption
        context['show_user'] = transition.show_owner
        if not context['show_user']:
            dest_owner = self.get_destination_owner()
            if dest_owner:
                context['dest_owner'] = dest_owner.username
            else:
                context['dest_owner'] = 'Nessuno'
        context['show_message'] = True
        context['cancel_url'] = self.get_cancel_url()
        return context


    # TODO change nuovo_stato => destination_state
    def dispatch(self, request, pk, nuovo_stato):
        self.destination_state = nuovo_stato
        if nuovo_stato in ['delegate', 'reject']:
            self.force_transition_type = nuovo_stato
        # TODO ??????
        self.object = self.get_object()
        return super(ChangeStateView, self).dispatch(request, pk=pk)


    def get_destination_owner(self):
        return self.get_transition().owner


    def get_destination_state(self):
        return self.get_transition().destination


    def get_transition_message(self):
        return self.get_transition().message


    def get_destination_suspended(self):
        return self.get_transition().is_suspend


    def get_form_kwargs(self):
        args = super(ChangeStateView, self).get_form_kwargs()
        transition = self.get_transition()
        args['require_owner'] = False
        args['require_msg'] = False

        if transition.show_owner:
            args['owner_choices'] = transition.get_potential_owners()
            if transition.destination_owner_mode != 'assign-optional':
                args['require_owner'] = True

        args['default_owner'] = transition.get_default_owner()
        args['require_msg'] = transition.require_message

        return args


    def form_valid(self, form):
        self.get_transition()
        owner_id = form.cleaned_data.get('owner', None)
        if owner_id:
            self.transition.set_owner(User.objects.get(pk=owner_id))
        elif self.transition.command in ('', 'release'):
            self.transition.set_owner(None)
        self.transition.set_message(form.cleaned_data.get('message', None))
        return super(ChangeStateView, self).form_valid(form)



class ObjectHistoryView(CachedGetObjectMixin, AccessDeniedMixin, DetailView):
    model = None
    template_name = "workflow/object_history.html"

    def get_context_data(self, *args, **kwargs):
        context = super(ObjectHistoryView, self).get_context_data(*args, **kwargs)
        states = self.object.wfm.get_states()
        context['states'] = states
        return context


    def access_denied_error(self, request, *args, **kwargs):
        if not self.get_object().wfm.can_read(request.user):
            return "L'utente non può accedere a questa risorsa."

