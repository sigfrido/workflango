# -*- coding: utf-8 -*-

from .models import State


class WFTransitionDescriptor(object):
    """
    Read-only descriptor for a potential workflow transition, used by the view layer.

    Obtained via instance.wfm.get_transition(dest_state, user). Encapsulates
    everything a template or view needs to render a transition button and the
    corresponding form: caption, owner selection, message requirement, allowed
    groups, and whether the transition is currently permitted.

    Special command strings ('release', 'delegate', 'assign', 'reject',
    'take-ownership', 'suspend', 'resume') are resolved to the appropriate
    destination state and owner automatically.

    Key properties:
    - destination / owner / message  — transition parameters
    - caption / is_reject / is_forward / is_free / is_take_ownership  — display hints
    - show_owner / require_message  — form field visibility
    - allowed() — True if transition_allowed() would pass for current user/state
    - execute() — perform the transition (calls obj.wfm.transition())
    """

    # destination_owner_modes = ('user', 'none', 'assign', 'last_owner') # , 'admin', 'random', 'workload'
    # TODO check errors (obj registered & managed, valid dest_state, can_reject...)
    def __init__(self, obj, dest_state, user, owner='auto', message=None, suspended=False):
        self._obj = obj
        self.wfconfig = obj.wfm_config
        self.user = user
        self._owner = owner
        self._message = message
        self._suspended = suspended
        dest_state = State.state_str(dest_state)
        if dest_state in ['release', 'delegate', 'assign', 'reject', 'take-ownership', 'suspend', 'resume']:
            self.command = dest_state
            if self.command == 'reject':
                prev_state = self.state.get_previous_state()
                self._destination = prev_state.state
                self._owner = self.state.user
            else:
                self._destination = self.state_str
            if self.command == 'release':
                self._owner = None
            elif self.command in ['take-ownership', 'suspend', 'resume']:
                self._owner = self.user
            if self.command == 'suspend':
                self._suspended = True
            elif self.command == 'resume':
                self._suspended = False
        else:
            self.command = ''
            self._destination = dest_state
        self.config = self.wfconfig[self.state_str]['reachable_states'].get(self._destination, None)
        if self._owner == 'auto':
            self.guess_owner()


    def guess_owner(self):
        if self.is_reject:
            self._owner = self.get_last_owner()
        else:
            dom = self.destination_owner_mode
            if dom == 'none':
                self._owner = None
            elif dom == 'user':
                self._owner = self.user
            elif dom == 'last_owner':
                self._owner = self.get_last_owner()
            else:
                self._owner = None
        if self._owner and not self._owner.id in [ow.id for ow in self.obj.get_candidate_users(for_state=self._destination, privileges='ea', active=True)]:
            self._owner = None


    @property
    def wfm(self):
        return self._obj.wfm

    def set_owner(self, owner):
        self._owner = owner


    @property
    def owner(self):
        return self._owner


    @property
    def obj(self):
        return self._obj


    @property
    def message(self):
        return self._message


    def set_message(self, message):
        self._message = message


    @property
    def is_suspend(self):
        return self._suspended


    @property
    def is_resume(self):
        if (not self._suspended) and self.state:
            prev_state = self.state.get_previous_state()
            if prev_state:
                return prev_state.suspended
        return False


    def allowed(self):
        try:
            return self.obj.wfm.transition_allowed(self.user, self.destination, self.owner, suspended=self._suspended)
        except Exception as e:
            self.error_msg = ";".join(e.messages)
            return False


    def execute(self):
        return self.obj.wfm.transition(self.user, self.destination, self.owner, self.message, suspended=self._suspended)


    def get_config(self, key, default=None):
        """Gets a value from transition configuration.
        Value can be a callable which is passed the transition instance
        """
        value = None
        if self.config:
            value = self.config.get(key, None)
        if not value:
            return default
        if callable(value):
            return value(self)
        return value


    @property
    def transition(self):
        return '%s_to_%s' % (self.state_str, self.destination)


    @property
    def destination(self):
        return self._destination


    @property
    def state(self):
        return self.obj.current_state


    @property
    def state_str(self):
        return State.state_str(self.state)

    def state_property(self, prop, defa=None):
        return self.state.wfm_state_config().get('properties', {}).get(prop, defa)

    @property
    def state_help_topic(self):
        return self.state_property('help_topic')

    @property
    def state_description(self):
        return self.state_property('description')


    # Transition properties

    @property
    def caption(self):
        caption = self.get_config('caption', '')
        if not caption:
            if self.is_take_ownership:
                caption = 'Prendi in carico'
            elif self.is_free:
                caption = 'Rilascia'
            elif self.is_reject:
                caption = 'Rimanda a ' + self.destination
            else:
                caption = 'Vai a: ' + self.destination
        return caption


    @property
    def is_forward(self):
        return not self.is_reject and not self.command


    @property
    def is_free(self):
        return (self.destination == self.state_str) and (self.state.owner == self.user)


    @property
    def is_take_ownership(self):
        return ((self.destination == self.state_str) and (self.state.owner is None))


    @property
    def is_backward(self):
        return not self.is_forward


    @property
    def is_hidden(self):
        hidden = self.get_config('hidden', None)
        return hidden


    @property
    def is_disabled(self):
        result = self.get_config('disabled', None)
        if (not result) and self.allowed_groups:
            result = not self.user.in_groups(self.allowed_groups)
        return result


    @property
    def is_reject(self):
        return self.get_config('reject', False)


    @property
    def require_message(self):
        require_message = self.get_config('require_message', None)
        if require_message == None:
            require_message = self.is_reject or self.command in ['delegate', 'reject', 'release', 'suspend'] or (self.command in ['take-ownership', 'assign'] and self.obj.current_state.owner and self.obj.current_state.owner != self.user)
        return require_message


    @property
    def show_owner(self):
        if self.command in ('take-ownership', 'reject', 'release', 'resubmit', 'release', 'suspend', 'resume'):
            return False
        return (
            (self.obj.wfm.can_admin(self.user)) # see #595 - User who can administer record in its present state can always assign destination owner
            or (self.command in ['delegate', 'assign'])
            or (self.destination_owner_mode in ['assign', 'assign-optional'])
        )


    @property
    def destination_owner_mode(self):
        dest = self.get_config('owner_mode', None)
        if not dest:
            # TODO map command transitions: take-ownership=self, release=none, delegate=assign,...
            dest = 'none'
        return dest


    @property
    def allowed_groups(self):
        return self.get_config('allowed_groups', [])


    def get_destination_state_property(self, prop, defa=None):
        return self.wfconfig.get_state_config(self.destination).get('properties', {}).get(prop, defa)

    def destination_description(self):
        return self.get_destination_state_property('description')

    def destination_help_topic(self):
        return self.get_destination_state_property('help_topic')


    def get_previous_different_state(self, state_str=None):
        state = self.obj.current_state
        if not state:
            return None
        return state.get_previous_different_state(state_str)


    def get_last_owner_for_phase(self, phase):
        state = self.state.find_last_state(phase)
        if state:
            return state.owner


    def get_last_owner(self):
        return self.get_last_owner_for_phase(self._destination)


    def get_default_owner(self):
        defa = self.get_config('default_owner', None)
        return defa if defa else self.get_last_owner()


    def get_potential_owners(self):
        user_is_admin = self.wfm.can_admin(self.user)
        perm = 'e' if not user_is_admin else 'ea'
        candidates = self.obj.get_candidate_users(self.destination, perm, True)
        pot_owners = [(user.id, user.wfm_display_str_assign()) for user in candidates]
        # Remove admin from potential owners for normal users, #592
        if not user_is_admin:
            # This shouldn't be needed, admin should have only 'a' privilege on records
            self._remove_users_from_owners((self.obj.wfm_config.admin(), ), pot_owners)
        if self.command in ['assign', 'delegate', 'reassign']:
            # Cannot delegate to myself or to current owner; owner is compulsory
            self._remove_users_from_owners((self.user, self.obj.current_state.owner), pot_owners)
        else:
            if (self.destination_owner_mode in ('assign-optional', 'none')):
                # Allow empty owner
                pot_owners.insert(0, (0, '---'))
        return pot_owners


    def _remove_users_from_owners(self, users, pot_owners):
        removable_ids = [user.id for user in users if user]
        for user_data in pot_owners:
            if user_data[0] in removable_ids:
                pot_owners.remove(user_data)













