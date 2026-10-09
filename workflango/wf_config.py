"""
Workflow Configuration object

SAMPLE WORKFLOW CONFIG

Model.configure_workflow(
    defaults = {
        'read' : ['GPV_APP_STAFF'],
        'admin' : ['APP_ADMIN','GPV_MODEL_ADMIN'],
        'edit' : ['GPV_MODEL_EDIT'],
        'properties' : {
            'edit_button_label' : 'Modifica',
            'help_topic' : 'workflow',
        }
    },

    config = (

        # Defines start phase
        (None, {
            'reachable_phases': {
                'aperta' : {},
            },
        }),

        ('aperta',  {
            'caption' : 'Aperta',
            'description' : 'Richiesta in lavorazione',
            'reachable_phases': {
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
            }
        }),

        ('inviata',  {
            'caption' : 'Inviata',
            'description' : 'Risposta inviata al richiedente',
            'is_closed' : True,
            'reachable_phases': {
                'aperta' : {
                    'reject' : True,
                },

            },
            'edit' : [], # Admin only
            'properties' : {
                'help_topic' : 'proc_richieste_risp',
            }
        }),

        ...

    )
)

"""
from copy import deepcopy

from django.contrib.auth import get_user_model

from django.conf import settings
from .i18n import wgettext_lazy
from .user_groups import user_in_groups, users_for_groups
from .exceptions import (
    WorkflowModelNotConfigured,
    InvalidWorkflowConfiguration,
    InvalidPhase,
    ConfigurationException,
)




# Builtin phase metafilters (values of the phase filter standing for several phases, #8)
PHASES_OPEN = 'phases_open'
PHASES_CLOSED = 'phases_closed'

# Builtin owner filter shortcuts (filters.USER_CHOICES): reserved for owner metafilter keys
OWNER_SHORTCUTS = ('me', 'me_or_none', 'none', 'someone', 'not_me', 'not_active', 'id')

# Values of a forward transition's 'button-style' → Bootstrap color (see WFTransitionDescriptor.button_style)
BUTTON_STYLES = {
    'default':   'primary',
    'info':      'info',
    'warning':   'warning',
    'success':   'success',
    'danger':    'danger',
    'secondary': 'secondary',
}


class WorkflowConfig(dict):
    """
    Workflow configuration for a model, stored as a dict keyed by phase name.

    Built by WorkflowModel.configure_workflow() from a tuple of
    (phase_name, config_dict) pairs; None as phase_name defines the entry point.
    Phase keys are coerced to str(20); None is kept as-is.

    Each phase entry is a dict with:
    - reachable_phases: {dest_phase: transition_config} — allowed next phases
    - read / edit / admin: lists of group names with the respective permission
    - caption: short name of the phase ("Approval"); required by check(), defaults to the
      phase key at runtime
    - description: one-line description; required by check(); tooltip of the transition
      buttons leading to the phase
    Long descriptions (Markdown: permissions, operations), used only by generate_wf_doc, are
    files <phase>.md in the description folder (configure_workflow(description_folder=...),
    default <app>/wf_doc/<model_name>/): see phase_long_description(), check_descriptions().
    - is_closed: bool — terminal phase; no further transitions expected
    - allow_release / allow_delegate: 'strict' | 'always' | 'no' | 'yes'
    - properties: arbitrary dict consumed by the view layer (help_topic, …)

    Reject transitions between adjacent phases are auto-configured from each forward
    transition config's 'allow-reject':
    - True (default): anyone who may act on the record can send it back;
    - 'admin': only members of the admin groups of the phase the record is sent back
      from (the generated reject gets those groups as 'allowed_groups');
    - False: no reject transition is generated.

    A forward transition config's 'button-style' ('default' | 'info' | 'warning' | 'success' |
    'danger' | 'secondary') sets the
    color of its button (see WFTransitionDescriptor.button_style).

    Class-level caches (_workflow_admin, _workflow_admins) are shared across all
    WorkflowConfig instances. Call clear_cached_admins() in tests that modify users.
    """

    _workflow_admin = None
    _workflow_admins = None

    def __init__(self, model, model_config, model_defaults=None, impersonable_users_func=None,
                 snapshot_serializer=None, description_folder=None,
                 phase_metafilters=None, owner_metafilters=None):
        super(WorkflowConfig, self).__init__()
        self._description_folder = description_folder
        self._phase_metafilters = dict(phase_metafilters or {})
        self._owner_metafilters = dict(owner_metafilters or {})
        self._model = model
        if model_defaults is None:
            model_defaults = {}
        if not isinstance(model_defaults, dict):
            raise InvalidWorkflowConfiguration(f"Parameter model_defaults for {self._model} must be a dict")
        self._model_defaults = model_defaults
        self._model_phases = []
        self._phase_texts = {}      # phase → texts as written in its own config (check_phase_texts)
        self._auto_rejects = set()  # (from, to) reject transitions generated automatically
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
            self._create_phase_config(key, conf_dict)

        self._model_phases = tuple(self._model_phases)
        self._autoconfig_reject_transitions()


    def _create_phase_config(self, key, conf_dict):
        new_key = self._register_valid_phase_key(key)
        current_config = self._get_default_phase_config()
        for (dest_phase, transition_config_dict) in conf_dict.get('reachable_phases', {}).items():
            dest_phase = str(dest_phase)
            current_config['reachable_phases'][dest_phase] = deepcopy(transition_config_dict)
        current_config['properties'].update(conf_dict.get('properties', {}))
        for custom_property in [k for k in conf_dict.keys() if k not in ['reachable_phases', 'properties']]:
            current_config[custom_property] = deepcopy(conf_dict[custom_property])
        # Phase texts are per-phase, never inherited from defaults
        for key_text in ('caption', 'description'):
            current_config[key_text] = conf_dict.get(key_text, '')
        if not current_config['caption']:
            current_config['caption'] = new_key or ''
        self._phase_texts[new_key] = {k: conf_dict[k] for k in ('caption', 'description')
                                      if k in conf_dict}
        self[new_key] = current_config


    def _register_valid_phase_key(self, key):
        if key is None:
            new_key = None
        else:
            new_key = str(key)
            if len(new_key) > 20:
                raise InvalidWorkflowConfiguration(f"Module {self._model} cannot be registered with workflow: configured phases must be coercible to char(20), {key} is not")
            self._model_phases.append(new_key)
        return new_key


    def _get_default_phase_config(self):
        current_config = {}
        current_config = deepcopy(self._model_defaults)
        current_config.setdefault('is_closed', False)
        current_config.setdefault('snapshot', False)
        current_config.setdefault('properties', {})
        current_config.setdefault('allow_release', 'strict')
        current_config['reachable_phases'] = {}
        return current_config


    def _autoconfig_reject_transitions(self):
        for (from_phase, from_phase_conf) in self.items():
            if from_phase:
                for (to_phase, from_reach_conf) in from_phase_conf['reachable_phases'].items():
                    button_style = from_reach_conf.get('button-style', 'default')
                    if button_style not in BUTTON_STYLES:
                        raise InvalidWorkflowConfiguration(
                            f"Invalid 'button-style' for {self._model}.{from_phase} -> {to_phase}: "
                            f"{button_style!r} (expected one of {', '.join(BUTTON_STYLES)})"
                        )
                    allow_reject = from_reach_conf.get('allow-reject', True)
                    if allow_reject not in (True, False, 'admin'):
                        raise InvalidWorkflowConfiguration(
                            f"Invalid 'allow-reject' for {self._model}.{from_phase} -> {to_phase}: "
                            f"{allow_reject!r} (expected True, False or 'admin')"
                        )
                    if allow_reject:
                        to_reach_conf = self[to_phase]['reachable_phases']
                        if not from_phase in to_reach_conf:
                            reject_conf = {'reject': True}
                            if allow_reject == 'admin':
                                reject_conf['allowed_groups'] = list(self[to_phase]['admin'])
                            to_reach_conf[from_phase] = reject_conf
                            self._auto_rejects.add((to_phase, from_phase))


    def phase_caption(self, phase):
        """Short name of the phase ('' for the None start phase)."""
        if phase is None:
            return ''
        return self.get_phase_config(phase).get('caption') or str(phase)

    def phase_description(self, phase):
        if phase is None:
            return ''
        return self.get_phase_config(phase).get('description', '')

    def description_folder(self):
        """(path, explicit) of the folder with the phases' long descriptions: the
        `description_folder` passed to configure_workflow (absolute, or relative to the model's
        app folder) or, if not set, <app folder>/wf_doc/<model_name>/."""
        from pathlib import Path
        from django.apps import apps
        meta = getattr(self._model, '_meta', None)
        app_path = Path(apps.get_app_config(meta.app_label).path) if meta else Path('.')
        if self._description_folder:
            return app_path / self._description_folder, True
        return app_path / 'wf_doc' / (meta.model_name if meta else ''), False

    def phase_long_description(self, phase):
        """Markdown of <description folder>/<phase>.md, '' if missing."""
        if phase is None:
            return ''
        folder, _ = self.description_folder()
        path = folder / f'{phase}.md'
        return path.read_text(encoding='utf-8') if path.is_file() else ''

    def check_descriptions(self):
        """Warnings (list of str, never raises) about the long descriptions: folder not
        found, files not matching any phase, phases without a file."""
        folder, explicit = self.description_folder()
        name = getattr(self._model, '__name__', self._model)
        if not folder.is_dir():
            kind = 'description_folder' if explicit else 'default description folder (description_folder not set)'
            return [f'{name}: {kind} not found: {folder}']
        files = {p.stem for p in folder.glob('*.md')}
        phases = set(self._model_phases)
        warnings = [f'{name}: {folder / (f + ".md")} does not match any phase' for f in sorted(files - phases)]
        warnings += [f'{name}: no long description for phase {p} ({folder / (p + ".md")})'
                     for p in self._model_phases if p not in files]
        return warnings

    # ---- filter metafilters (#8)

    def phase_metafilters(self):
        """{key: (label, phases)} usable as values of the phase filter: the builtin
        phases_open / phases_closed, then the model's own (configure_workflow(phase_metafilters=)).
        `phases` is a list of phase keys or a callable(request, wfm_config) -> iterable of phases."""
        return {
            PHASES_OPEN: (wgettext_lazy('Open phases'), lambda request, cfg: cfg.get_phases_list(closed=False)),
            PHASES_CLOSED: (wgettext_lazy('Closed phases'), lambda request, cfg: cfg.get_phases_list(closed=True)),
            **self._phase_metafilters,
        }

    def owner_metafilters(self):
        """{key: (label, fn)} of the model's owner metafilters (configure_workflow(owner_metafilters=)):
        fn(request) -> users (queryset or iterable), or fn(lookup, request) -> Q."""
        return dict(self._owner_metafilters)

    def expand_phase_metafilter(self, key, request=None):
        """Phase keys the metafilter `key` stands for (KeyError if not a metafilter)."""
        _label, phases = self.phase_metafilters()[key]
        if callable(phases):
            phases = phases(request, self)
        return [str(p) for p in phases]

    def check_metafilters(self):
        name = getattr(self._model, '__name__', self._model)
        for key, value in self._phase_metafilters.items():
            if key in self._model_phases or key in (PHASES_OPEN, PHASES_CLOSED):
                raise InvalidWorkflowConfiguration(
                    f"Phase metafilter {name}.{key}: key clashes with a phase or a builtin metafilter.")
            if not (isinstance(value, (tuple, list)) and len(value) == 2):
                raise InvalidWorkflowConfiguration(f"Phase metafilter {name}.{key} must be (label, phases).")
            phases = value[1]
            if not callable(phases):
                unknown = [p for p in phases if str(p) not in self._model_phases]
                if unknown:
                    raise InvalidWorkflowConfiguration(
                        f"Phase metafilter {name}.{key}: unknown phases {', '.join(map(str, unknown))}.")
        for key, value in self._owner_metafilters.items():
            if str(key).isdigit() or key in OWNER_SHORTCUTS:
                raise InvalidWorkflowConfiguration(
                    f"Owner metafilter {name}.{key}: key must not be numeric nor a builtin shortcut.")
            if not (isinstance(value, (tuple, list)) and len(value) == 2 and callable(value[1])):
                raise InvalidWorkflowConfiguration(f"Owner metafilter {name}.{key} must be (label, callable).")

    def is_auto_reject(self, from_phase, to_phase):
        """True if from_phase → to_phase is a reject generated from to_phase's forward
        transition (see _autoconfig_reject_transitions), not declared in the config."""
        return (from_phase, to_phase) in self._auto_rejects

    def get_phase_config(self, phase):
        try:
            return self[phase]
        except:
            raise InvalidPhase(f"{self._model}[{phase}]")


    def get_phases_list(self, closed=None):
        """
        Returns the list of phases in the same order they are defined in config, bar the first None phase
        """
        try:
            phases = self._model_phases
            if closed != None:
                phases = [phase for phase in phases if self[phase].get('is_closed', False) == closed]
            return phases
        except:
            raise WorkflowModelNotConfigured(f"{self._model}")


    def get_phase_order(self, phase):
        """
        Returns the index of the given phase
        """
        if phase is None:
            return 0
        phases = self.get_phases_list()
        phase = str(phase)
        if phase in phases:
            return phases.index(phase) + 1
        raise InvalidPhase(f"{self._model}[{phase}]")


    def editors_for_phase(self, phase, admin_also=True):
        try:
            config = self[phase]
            if admin_also:
                groups = config['edit'] + config['admin']
            else:
                groups = config['edit']
            return list(set(groups))
        except:
            raise InvalidPhase(f"Configurazione per {self._model}.{phase} non trovata")


    def get_candidate_users_for_phase(self, phase, privileges='ea', active=None):
        config = self[phase]
        groups = []
        for priv in ('read', 'edit', 'admin'):
            if priv[0] in privileges:
                groups = groups + config[priv]
        owner_groups = list(set(groups))
        users = users_for_groups(owner_groups, active)
        return users


    def can_create(self, user):
        return user_in_groups(user, self.editors_for_phase(None))


    def get_phases_for_permissions(self, user, permissions):
        """
        which phases allow the given permissions to this user?
        TODO remove me?
        """
        out = []
        user_groups = user.groups.all().values_list('name', flat=True)[:]
        user_groups = set(user_groups)

        for configured_phase in [x for x in self.keys() if x is not None]:
            perm_groups = []
            for perm in ('read', 'edit', 'admin'):
                if perm[0] in permissions:
                    perm_groups += self[configured_phase][perm]
            perm_groups = set(perm_groups)
            if len(user_groups & perm_groups):
                out.append(configured_phase)
        return out


    def admin(self):
        cls = self.__class__
        if cls._workflow_admin == None:
            try:
                admin_name = getattr(settings, 'WF_ADMIN', None)
                if admin_name:
                    cls._workflow_admin = get_user_model().objects.get(username=admin_name)
                else:
                    cls._workflow_admin = get_user_model().objects.get(is_superuser=True)
            except:
                raise ConfigurationException('Utente admin o superuser non trovato o non univoco')
        return cls._workflow_admin


    def is_admin(self, user):
        if user.is_superuser:
            return True
        admin_name = getattr(settings, 'WF_ADMIN', None)
        if admin_name and user.username == admin_name:
            return True
        admin_group = getattr(settings, 'WF_ADMIN_GROUP', None)
        if admin_group and user_in_groups(user, admin_group):
            return True
        return False
        # cls = self.__class__
        # if cls._workflow_admins == None:
        #     cls._workflow_admins = tuple(get_user_model().objects.filter(groups__name=settings.WF_ADMIN_GROUP).values_list('id', flat=True))
        #     if not len(cls._workflow_admins):
        #         raise ConfigurationException('Nessun utente trovato per il gruppo dichiarato in WF_ADMIN_GROUP')
        # return user.id in cls._workflow_admins


    @classmethod
    def clear_cached_admins(cls):
        cls._workflow_admin = None
        cls._workflow_admins = None


    def get_impersonable_users(self, user):
        """
        Returns a queryset of users that ``user`` is allowed to impersonate in this workflow.

        Default: superuser or WF_ADMIN_GROUP members can impersonate any
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
        if self.is_admin(user):
            return get_user_model().objects.filter(is_active=True).exclude(pk=user.pk)
        return get_user_model().objects.none()


    def check(self):
        self.check_unreachable_phases()
        self.check_defined_groups()
        self.check_config_values()
        self.check_has_terminal_phase()
        self.check_phase_texts()
        self.check_metafilters()

    def check_phase_texts(self):
        """Every phase (but the None start phase) must declare a non-empty caption and
        description, both strings. (Long descriptions are files: see check_descriptions().)"""
        nome = getattr(self._model, '__name__', self._model)
        for phase in self._model_phases:
            testi = self._phase_texts.get(phase, {})
            for key in ('caption', 'description'):
                if not testi.get(key):
                    raise InvalidWorkflowConfiguration(
                        f"Missing '{key}' in phase {nome}.{phase}.")
            for key, valore in testi.items():
                if not isinstance(valore, str):
                    raise InvalidWorkflowConfiguration(
                        f"'{key}' of phase {nome}.{phase} must be a string.")


    def check_unreachable_phases(self):
        """
        Must be able to reach any phase starting from None
        """
        reachable = {}
        for phase in self.keys():
            reachable[phase] = False

        self.reach_phases_from(None, reachable)

        for phase in self._model_phases:
            if not reachable[phase]:
                raise InvalidWorkflowConfiguration(f'Unreachable phase for {self._model}: {phase}.')


    def reach_phases_from(self, phase, reachable):
        reachable[phase] = True
        reachable_phases = self[phase]['reachable_phases']
        for reach in reachable_phases:
            if reach not in reachable:
                raise InvalidWorkflowConfiguration(f'Undefined phase for model {self._model}: phases[{phase}].reachable_phases[{reach}]')
            if not reachable[reach]:
                self.reach_phases_from(reach, reachable)


    def check_defined_groups(self):
        wfgroups = [group for (group, descr) in settings.WF_USERS_GROUPS]
        for phase in self.keys():
            for priv in ['read', 'edit', 'admin']:
                for group in self[phase][priv]:
                    if not group in wfgroups:
                        raise InvalidWorkflowConfiguration(f'Undefined group: {self._model}.phases[{phase}][{priv}] = {group}')


    def check_config_values(self):
        for phase in self.keys():
            for (key, default, values) in (
                ('allow_release', 'strict', ('no', 'always', 'strict')),
                ('allow_delegate', 'yes', ('no', 'yes')),
            ):
                value = self[phase].get(key, default)
                if not value in values:
                    raise InvalidWorkflowConfiguration(f'Undefined value for {key} in phase {self._model.__name__}.{phase}: {value}.')


    def check_has_terminal_phase(self):
        """
        At least one non-None phase must be terminal (is_closed=True), or an
        instance could never reach a final state.
        """
        if not any(self[phase].get('is_closed', False) for phase in self._model_phases):
            raise InvalidWorkflowConfiguration(f'No terminal phase (is_closed=True) declared for {self._model}.')

        # TODO destination_owner_mode: none, user, last_owner, assign, assign-optional
#
#            allow_release = self[phase].get('allow_release', 'strict')
#            if not allow_release in ('no', 'always', 'strict'):
#                raise InvalidWorkflowConfiguration('Undefined value for allow_release in phase %s.%s: %s:' % (self._model.__name__, phase, allow_release))
#            allow_delegate = self[phase].get('allow_delegate', 'yes')
#            if not allow_delegate in ('no', 'yes'):
#                raise InvalidWorkflowConfiguration('Undefined value for allow_delegate in phase %s.%s: %s:' % (self._model.__name__, phase, allow_delegate))


