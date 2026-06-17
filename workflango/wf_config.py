"""
Workflow Configuration object

SAMPLE WORKFLOW CONFIG

Model.configure_workflow(
    defaults = {
        'read' : ['GPV_APP_STAFF'],
        'admin' : ['GPV_APP_ADMIN','GPV_MODEL_ADMIN'],
        'edit' : ['GPV_MODEL_EDIT'],
        'properties' : {
            'edit_button_label' : 'Modifica',
            'help_topic' : 'workflow',
            'description' : '',
        }
    },

    config = (

        # Defines start phase
        (None, {
            'reachable_states': {
                'aperta' : {},
            },
        }),

        ('aperta',  {
            'reachable_states': {
                'inviata' : {
                    'caption' : 'Risposta inviata',
                    'owner_mode' : 'none',
                    'allowed_groups' : ['GPV_CHIUDI_RISP'] # defaults to edit groups
                },

                ...

            },
            'edit' : ['GPV_MODEL_EDIT', 'GPV_CHIUDI_RISP'],
            'properties' : {
                'allow_release': 'strict',
                'help_topic' : 'proc_richieste_risp',
                'description' : u"BlaBla",
            }
        }),

        ('inviata',  {
            'is_closed' : True,
            'reachable_states': {
                'aperta' : {
                    'reject' : True,
                },

            },
            'edit' : [], # Admin only
            'properties' : {
                'help_topic' : 'proc_richieste_risp',
                'description' : u"BlaBla",
            }
        }),

        ...

    )
)

"""
from copy import deepcopy

from django.contrib.auth.models import User

from django.conf import settings
from .user_groups import user_in_groups, users_for_groups
from .exceptions import (
    WorkflowModelNotConfigured,
    InvalidWorkflowConfiguration,
    InvalidState,
    ConfigurationException,
)



class WorkflowConfig(dict):
    """
    Workflow configuration for a model, stored as a dict keyed by state name.

    Built by WorkflowModel.configure_workflow() from a tuple of
    (state_name, config_dict) pairs; None as state_name defines the entry point.
    State keys are coerced to str(20); None is kept as-is.

    Each state entry is a dict with:
    - reachable_states: {dest_state: transition_config} — allowed next states
    - read / edit / admin: lists of group names with the respective permission
    - is_closed: bool — terminal state; no further transitions expected
    - allow_release / allow_delegate: 'strict' | 'always' | 'no' | 'yes'
    - properties: arbitrary dict consumed by the view layer (help_topic, description, …)

    Reject transitions between adjacent states are auto-configured unless
    'allow-reject': False is set on a transition config.

    Class-level caches (_workflow_admin, _workflow_admins) are shared across all
    WorkflowConfig instances. Call clear_cached_admins() in tests that modify users.
    """

    _workflow_admin = None
    _workflow_admins = None

    def __init__(self, model, model_config, model_defaults=None, impersonable_users_func=None, snapshot_serializer=None):
        super(WorkflowConfig, self).__init__()
        self._model = model
        if model_defaults is None:
            model_defaults = {}
        if not isinstance(model_defaults, dict):
            raise InvalidWorkflowConfiguration(f"Parameter model_defaults for {self._model} must be a dict")
        self._model_defaults = model_defaults
        self._model_states = []
        self._impersonable_users_func = impersonable_users_func
        self._snapshot_serializer = snapshot_serializer
        self._create_model_config(model_config)


    def _create_model_config(self, model_config):
        if not isinstance(model_config, tuple):
            raise InvalidWorkflowConfiguration(f"Parameter model_config for {self._model} must be a tuple")
        for element in model_config:
            if isinstance(element, dict):
                conf_dict = element
                key = conf_dict['name']
            elif isinstance(element, tuple) and len(element) == 2:
                key = element[0]
                conf_dict = element[1]
            else:
                raise InvalidWorkflowConfiguration(f"Parameter model_config for {self._model} must be a tuple of dict with key name or a tuple of (name, dict)")
            self._create_state_config(key, conf_dict)

        self._model_states = tuple(self._model_states)
        self._autoconfig_reject_transitions()


    def _create_state_config(self, key, conf_dict):
        new_key = self._register_valid_state_key(key)
        current_config = self._get_default_state_config()
        for (dest_state, transition_config_dict) in conf_dict.get('reachable_states', {}).items():
            dest_state = str(dest_state)
            current_config['reachable_states'][dest_state] = deepcopy(transition_config_dict)
        current_config['properties'].update(conf_dict.get('properties', {}))
        for custom_property in [k for k in conf_dict.keys() if k not in ['reachable_states', 'properties']]:
            current_config[custom_property] = deepcopy(conf_dict[custom_property])
        self[new_key] = current_config


    def _register_valid_state_key(self, key):
        if key is None:
            new_key = None
        else:
            new_key = str(key)
            if len(new_key) > 20:
                raise InvalidWorkflowConfiguration(f"Module {self._model} cannot be registered with workflow: configured states must be coercible to char(20), {key} is not")
            self._model_states.append(new_key)
        return new_key


    def _get_default_state_config(self):
        current_config = {}
        current_config = deepcopy(self._model_defaults)
        current_config.setdefault('is_closed', False)
        current_config.setdefault('snapshot', False)
        current_config.setdefault('properties', {})
        current_config.setdefault('allow_release', 'strict')
        current_config['reachable_states'] = {}
        return current_config


    def _autoconfig_reject_transitions(self):
        for (from_state, from_state_conf) in self.items():
            if from_state:
                for (to_state, from_reach_conf) in from_state_conf['reachable_states'].items():
                    if from_reach_conf.get('allow-reject', True):
                        to_reach_conf = self[to_state]['reachable_states']
                        if not from_state in to_reach_conf:
                            to_reach_conf[from_state] = { 'reject' : True }


    def get_state_config(self, state):
        try:
            return self[state]
        except:
            raise InvalidState(f"{self._model}[{state}]")


    def get_states_list(self, closed=None):
        """
        Returns the list of states in the same order they are defined in config, bar the first None state
        """
        try:
            states = self._model_states
            if closed != None:
                states = [state for state in states if self[state].get('is_closed', False) == closed]
            return states
        except:
            raise WorkflowModelNotConfigured(f"{self._model}")


    def get_state_order(self, state):
        """
        Returns the index of the given state
        """
        if state is None:
            return 0
        states = self.get_states_list()
        state = str(state)
        if state in states:
            return states.index(state) + 1
        raise InvalidState(f"{self._model}[{state}]")


    def editors_for_state(self, state, admin_also=True):
        try:
            config = self[state]
            if admin_also:
                groups = config['edit'] + config['admin']
            else:
                groups = config['edit']
            return list(set(groups))
        except:
            raise InvalidState(f"Configurazione per {self._model}.{state} non trovata")


    def get_candidate_users_for_state(self, state, privileges='ea', active=None):
        config = self[state]
        groups = []
        for priv in ('read', 'edit', 'admin'):
            if priv[0] in privileges:
                groups = groups + config[priv]
        owner_groups = list(set(groups))
        users = users_for_groups(owner_groups, active)
        return users


    def can_create(self, user):
        return user_in_groups(user, self.editors_for_state(None))


    def get_states_for_permissions(self, user, permissions):
        """
        which states allow the given permissions to this user?
        TODO remove me?
        """
        out = []
        user_groups = user.groups.all().values_list('name', flat=True)[:]
        user_groups = set(user_groups)

        for configured_state in [x for x in self.keys() if x is not None]:
            perm_groups = []
            for perm in ('read', 'edit', 'admin'):
                if perm[0] in permissions:
                    perm_groups += self[configured_state][perm]
            perm_groups = set(perm_groups)
            if len(user_groups & perm_groups):
                out.append(configured_state)
        return out


    def admin(self):
        cls = self.__class__
        if cls._workflow_admin == None:
            try:
                cls._workflow_admin = User.objects.get(username=settings.WORKFLOW_ADMIN)
            except:
                raise ConfigurationException('Utente admin non trovato o non univoco')
        return cls._workflow_admin


    def is_admin(self, user):
        cls = self.__class__
        if cls._workflow_admins == None:
            cls._workflow_admins = tuple(User.objects.filter(groups__name=settings.WORKFLOW_ADMIN_GROUP).values_list('id', flat=True))
            if not len(cls._workflow_admins):
                raise ConfigurationException('Nessun utente trovato per il gruppo dichiarato in WORKFLOW_ADMIN_GROUP')
        return user.id in cls._workflow_admins


    @classmethod
    def clear_cached_admins(cls):
        cls._workflow_admin = None
        cls._workflow_admins = None


    def get_impersonable_users(self, user):
        """
        Returns a queryset of users that ``user`` is allowed to impersonate in this workflow.

        Default: superuser or WORKFLOW_ADMIN_GROUP members can impersonate any
        other active user; everyone else gets an empty queryset.

        Override by passing ``impersonable_users`` to ``configure_workflow()``::

            MyModel.configure_workflow(
                config=...,
                impersonable_users=lambda user: UserDelegation.delegates_for(user),
            )

        The callable receives the requesting user and must return a queryset or
        iterable of User instances.
        """
        if self._impersonable_users_func is not None:
            return self._impersonable_users_func(user)
        admin_group = getattr(settings, 'WORKFLOW_ADMIN_GROUP', None)
        if user.is_superuser or (admin_group and user_in_groups(user, admin_group)):
            return User.objects.filter(is_active=True).exclude(pk=user.pk)
        return User.objects.none()


    def check(self):
        self.check_unreachable_states()
        self.check_defined_groups()
        self.check_config_values()


    def check_unreachable_states(self):
        """
        Must be able to reach any state starting from None
        """
        reachable = {}
        for state in self.keys():
            reachable[state] = False

        self.reach_states_from(None, reachable)

        for state in self._model_states:
            if not reachable[state]:
                raise InvalidWorkflowConfiguration(f'Unreachable state for {self._model}: {state}.')


    def reach_states_from(self, state, reachable):
        reachable[state] = True
        reachable_states = self[state]['reachable_states']
        for reach in reachable_states:
            if reach not in reachable:
                raise InvalidWorkflowConfiguration(f'Undefined state for model {self._model}: states[{state}].reachable_states[{reach}]')
            if not reachable[reach]:
                self.reach_states_from(reach, reachable)


    def check_defined_groups(self):
        wfgroups = [group for (group, descr) in settings.WORKFLOW_USERS_GROUPS]
        for state in self.keys():
            for priv in ['read', 'edit', 'admin']:
                for group in self[state][priv]:
                    if not group in wfgroups:
                        raise InvalidWorkflowConfiguration(f'Undefined group: {self._model}.states[{state}][{priv}] = {group}')


    def check_config_values(self):
        for state in self.keys():
            for (key, default, values) in (
                ('allow_release', 'strict', ('no', 'always', 'strict')),
                ('allow_delegate', 'yes', ('no', 'yes')),
            ):
                value = self[state].get(key, default)
                if not value in values:
                    raise InvalidWorkflowConfiguration(f'Undefined value for {key} in state {self._model.__name__}.{state}: {value}.')

        # TODO destination_owner_mode: none, user, last_owner, assign, assign-optional
#
#            allow_release = self[state].get('allow_release', 'strict')
#            if not allow_release in ('no', 'always', 'strict'):
#                raise InvalidWorkflowConfiguration('Undefined value for allow_release in state %s.%s: %s:' % (self._model.__name__, state, allow_release))
#            allow_delegate = self[state].get('allow_delegate', 'yes')
#            if not allow_delegate in ('no', 'yes'):
#                raise InvalidWorkflowConfiguration('Undefined value for allow_delegate in state %s.%s: %s:' % (self._model.__name__, state, allow_delegate))



