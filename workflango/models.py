# -*- coding: utf-8 -*-

from django.conf import settings
from django.db import models
from django.db import transaction
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractUser
from django.urls import reverse
from django.core.exceptions import ObjectDoesNotExist, ValidationError
import django.dispatch
from .user_groups import user_in_groups
from .exceptions import UnmanagedObject, TransitionNotAllowed, StaleObject

from .exceptions import get_exception_error_msg



# Signals

# providing_args=["instance", "prev_state", "cur_state"]
transition_done = django.dispatch.Signal()


# TODO move me in settings? Use gettext?
TRANS_TYPE_MAP = {
    None            : 'Non definita',
    'undefined'     : 'Non definita',
    'new'           : 'Inserimento',
    'delegate'      : 'Delega',
    'change_assign' : 'Transizione e assegnazione',
    'reject'        : 'Rifiuto',
    'resubmit'      : 'Ri-invio',
    'assign'        : 'Assegnazione',
    'reassign'      : 'Riassegnazione',
    'change'        : 'Transizione',
    'release'       : 'Rilascio',
    'snatch'        : 'Appropriazione',
    'take'          : 'Presa in carico',
    'suspend'       : 'Sospensione',
    'resume'        : 'Ripresa',
}


class State(models.Model):
    """
    A single node in the workflow history of a WorkflowModel instance.

    States form a doubly-linked list (previous_state / next_state). The node
    where next_state is None is the *current* state; all others are history.
    A denormalised pointer wfm_state on the owner instance always points to the
    current State, avoiding a query on every access.

    Key fields:
    - phase: short string identifying the workflow phase (max 20 chars)
    - owner: the user currently responsible for the object (nullable = unassigned)
    - user: the user who triggered the transition into this state
    - transition_type: auto-derived category (new/assign/delegate/reject/…)
    - suspended: soft-lock that blocks further transitions until resumed
    - unread: True when the owner has not yet viewed the object in this state
    - impersonated_by: set when an admin performed the transition impersonating another user;
      `user` holds the impersonated identity, `impersonated_by` the real actor
    - snapshot: optional JSON snapshot of the object at transition time (audit/rollback)
    """

    # object reference through GenericForeignKey
    content_type_object = models.ForeignKey(ContentType, models.CASCADE)
    id_object = models.PositiveIntegerField()
    instance = GenericForeignKey('content_type_object', 'id_object')

    phase = models.CharField(max_length=20)

    # datetime of transition from previous state
    state_date = models.DateTimeField(auto_now_add=True)

    # owner user
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
        related_name='states', on_delete=models.PROTECT)

    # user responsible for the transition to current state
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    # link to next state
    next_state = models.OneToOneField('self', null=True, blank=True,
        related_name='_previous_state', unique=True, on_delete=models.PROTECT)

    # link to previous state
    previous_state = models.OneToOneField('self', null=True, blank=True,
        related_name='_next_state', unique=True, on_delete=models.PROTECT)

    # optional message for the state transition
    message = models.TextField(null=True, blank=True)

    # transition type
    transition_type = models.CharField(max_length=20)

    # Flags a (temporary) inactivity on the instance until further notice from the owner
    suspended = models.BooleanField(default=False)

    # The state record and updated instance has not been read by its owner
    unread = models.BooleanField(default=False)

    # When set, this transition was performed by an admin impersonating another user.
    # user = the impersonated identity; impersonated_by = the real admin acting.
    impersonated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, 
        related_name='+', on_delete=models.SET_NULL)

    # Optional JSON snapshot of the object at the time of transition (audit/rollback).
    snapshot = models.JSONField(null=True, blank=True)


    @classmethod
    def phase_str(cls, state, for_none=None):
        if state == None:
            return for_none
        if isinstance(state, State):
            return state.phase
        try:
            return str(state)
        except:
            raise TypeError("New state must be coercible to 20 chars string")


    def __init__(self, *args, **kwargs):
        super(State, self).__init__(*args, **kwargs)
        self.cached_instance = None


    def __str__(self):
        """
        Unicode should or should not be used as a shortcut to state.state?
        """
        return f'State: {self.phase}'


    def get_instance(self):
        if not self.cached_instance:
            self.cached_instance = self.instance
        return self.cached_instance


    def get_previous_state(self):
        if not hasattr(self, '_previous_state_cached'):
            try:
                self._previous_state_cached = self.previous_state
            except:
                self._previous_state_cached = None
        return self._previous_state_cached


    def get_previous_different_state(self, state_str=None):
        """
        Returns previous state different from current one, ignoring all the delegate/suspend transitions in the current state
        """
        if not state_str:
            state_str = self.phase
        elif self.phase != state_str:
            return None
        state = self
        while state and state.phase == state_str:
            state = state.get_previous_state()
        if state:
            return state.phase
        return None


    def find_last_state(self, state):
        """
        Returns the nearest instance's State before this one which has the given state
        """
        try:
            return State.objects.filter(content_type_object=self.content_type_object, id_object=self.id_object, phase=state, pk__lt=self.pk).order_by('-id')[0]
        except:
            return None


    def wfm_state_config(self):
        """
        Returns configuration for current state
        """
        return self.get_instance().wfm_config[self.phase]


    def get_state_order(self, relative_to=None):
        """
        Returns definition order for current state
        """
        inst = self.get_instance()
        my_state_order = inst.wfm_config.get_state_order(self.phase)
        other_state_order = inst.wfm_config.get_state_order(relative_to) if relative_to else 0
        return my_state_order - other_state_order



    def get_state_property(self, property_name):
        cfg = self.wfm_state_config()
        properties = cfg.get("properties", {})
        value = properties.get(property_name, None)
        return value



    def is_closed(self):
        cfg = self.wfm_state_config()
        return cfg.get('is_closed', False)


    @property
    def can_release(self):
        """
        Tells if the owner can release the record. In strict mode, a user can
        release only after a take/snatch/assign on the current state.
        """
        if self.suspended:
            return False
        conf = self.wfm_state_config()
        allow_release = conf.get('allow_release', 'strict')
        if allow_release == 'no' or not self.owner:
            return False
        elif allow_release == 'always' or self.get_instance().wfm.can_admin(self.owner):
            return True
        # default = 'strict'
        # TODO gestire le fasi terminali (attuata, revocata...): in teoria dovrebbe sempre essere consentito il release???
        if self.transition_type in ['delegate', 'assign', 'change_assign', 'reassign']:
            return False
        return True


    @property
    def can_reject(self):
        """
        Check if current state can be rejected to the previous one
        """
        # TODO and current.user = previous.owner ????
        return self.transition_type in ['assign', 'reassign', 'change_assign', 'delegate', 'resubmit']


    @property
    def can_delegate(self):
        """
        Is delegation allowed?
        """
        if self.suspended:
            return False
        conf = self.wfm_state_config()
        allow_delegate = conf.get('allow_delegate', 'yes')
        return (allow_delegate != 'no') or self.get_instance().wfm.can_admin(self.owner)


    def get_transition_type(self, previous_state):
        if not previous_state:
            return 'new'

        if self.suspended:
            return 'suspend'

        prev_prev = previous_state.get_previous_state()

        if prev_prev and self.owner == previous_state.user and self.user == previous_state.owner and self.phase == prev_prev.phase:
            if previous_state.transition_type == 'reject':
                return 'resubmit'
            if previous_state.transition_type in ['delegate', 'change_assign', 'assign', 'reassign', 'resubmit']:
                return 'reject'

        if self.phase != previous_state.phase:
            if not self.owner:
                return 'change'
            return 'change_assign'

        if not self.owner:
            return 'release'

        if self.owner == self.user:
            if previous_state.owner:
                if self.user == previous_state.owner:
                    return 'resume'
                return 'snatch'
            return 'take'

        if self.owner != previous_state.owner:
            if self.user != previous_state.owner:
                if not previous_state.owner:
                    return 'assign'
                return 'reassign'
            return 'delegate'

        # Should never reach here
        return 'undefined'



    def transition_type_display(self):
        if self.transition_type and self.transition_type in TRANS_TYPE_MAP:
            return TRANS_TYPE_MAP[self.transition_type]
        return TRANS_TYPE_MAP[None]



    def save(self, *args, **kwargs):
        if not self.transition_type:
            self.transition_type = self.get_transition_type(self.get_previous_state())
        if self.message == '':
            self.message = None
        super(State, self).save(*args, **kwargs)


# Moved here to avoid cyclic dependency State - WFTransdescr
from .wf_transition import WFTransitionDescriptor
from .wf_config import WorkflowConfig


class WorkflowModel(models.Model):
    """
    Abstract base model that attaches the workflow engine to any Django model.

    Usage::

        class MyDocument(WorkflowModel):
            title = models.CharField(max_length=200)

        MyDocument.configure_workflow(config=(...), defaults={...})

    After configuration, each instance exposes:
    - instance.wfm  — InstanceWorkflowManager with transition/permission methods
    - instance.current_state  — the current State node (None until first transition)
    - instance.wfm_state  — OneToOne FK to the current State (DB-level pointer)
    - instance.states  — GenericRelation to all historical State nodes
    """

    class Meta:
        abstract = True

    states = GenericRelation(State, content_type_field='content_type_object', object_id_field='id_object', editable=False)
    wfm_state = models.OneToOneField(State, null=True, blank=True, editable=False, related_name='+', on_delete=models.SET_NULL)

    @classmethod
    def get_content_type(cls):
        return ContentType.objects.get_for_model(cls)


    @classmethod
    def configure_workflow(cls, config=None, defaults=None, impersonable_users=None, snapshot_serializer=None):
        """
        Creates the workflow configuration for this model.

        ``impersonable_users``: optional callable ``(user) -> queryset`` returning the
        users ``user`` is allowed to impersonate. Default: superuser / WORKFLOW_ADMIN / WORKFLOW_ADMIN_GROUP.

        ``snapshot_serializer``: optional DRF serializer class used by the default
        ``get_workflow_snapshot()`` implementation to produce the snapshot dict.
        If omitted, ``get_workflow_snapshot()`` returns ``None`` (no snapshot).
        """
        if hasattr(cls, 'wfm_config'):
            return
        if not config:
            config = getattr(cls, 'workflow_phases', None)
        if not defaults:
            defaults = getattr(cls, 'workflow_defaults', {})
        cls.wfm_config = WorkflowConfig(
            cls, config, defaults,
            impersonable_users_func=impersonable_users,
            snapshot_serializer=snapshot_serializer,
        )


    @property
    def wfm(self):
        """
        Returns the InstanceWorkflowManager for this instance
        """
        if not hasattr(self, '_wfm_inst'):
            self._wfm_inst = InstanceWorkflowManager(self)
        return self._wfm_inst


    def materialize_current_state(self, state):
        """
        Called by transition(), copies current state information to instance
        (Currently only state object id)
        """
        self.wfm_state = state
        self.save(update_fields = ['wfm_state'])


    def reload_from_db(self):
        """
        Returns a fresh copy of the instance from the DB.
        Useful in case of StaleObject exceptions.
        """
        return self.__class__.objects.get(pk=self.pk)


    def lock_instance(self):
        """
        Locks the instance row for the duration of the current transaction.

        Behaviour by backend:
        - PostgreSQL / MySQL 8.0+ / Oracle: SELECT FOR UPDATE NOWAIT — raises
          OperationalError immediately if another transaction holds the lock.
        - MySQL < 8.0 / MariaDB < 10.3: SELECT FOR UPDATE (blocking) — waits
          for the lock; no NOWAIT error, but no instant failure either.
        - SQLite: no-op (Django silently skips FOR UPDATE on SQLite).
        """
        from django.db import connection
        if not connection.features.has_select_for_update:
            return self
        nowait = connection.features.has_select_for_update_nowait
        return self.__class__.objects.select_for_update(nowait=nowait).filter(pk=self.pk)[0]


    @property
    def current_state(self):
        """
        helper property; caches self into state instance
        """
        if self.wfm_state and not self.wfm_state.cached_instance:
            self.wfm_state.cached_instance = self
        return self.wfm_state


    def current_state_str(self, for_none=''):
        return State.phase_str(self.current_state, for_none)


    def get_workflow_snapshot(self, new_phase):  # noqa: ARG002
        """
        Returns a JSON-serialisable dict representing this instance at the moment of a
        transition, to be stored in ``State.snapshot``.

        Called automatically by ``transition()`` when:
        - ``settings.WORKFLANGO_SNAPSHOT_ENABLED`` is ``True``
        - the source state's config has ``'snapshot': True``

        Default implementation: uses the serializer class declared via
        ``configure_workflow(snapshot_serializer=MySerializer)``, or returns ``None``
        if none is configured.  Override for custom logic (field filtering, per-phase
        content, etc.); ``new_phase`` is the destination phase of the transition.
        """
        serializer_class = self.wfm_config._snapshot_serializer
        if serializer_class is None:
            return None
        return dict(serializer_class(self).data)


    def reload_current_state(self):
        """
        Returns the last (current) State instance associated with this instance,
        i.e. the one with the next_state attribute set to None.
        """
        instance_type = self.__class__.get_content_type()
        try:
            last_state = State.objects.get(content_type_object=instance_type,
                    id_object=self.pk, next_state=None)
        except ObjectDoesNotExist:
            last_state = None
        return last_state


    # Required by history_view
    def get_absolute_url(self):
        view_name = f'{self.__class__.__name__.lower()}_detail'
        # TODO should remove this dependency upon url resolver
        url = reverse(view_name, kwargs={'pk': self.pk})
        return url


    # Required by WF error messages - should briefly identify the object
    def get_brief_name(self):
        return str(self)


    def user_can_delete_error(self, user):
        if not self.wfm.is_owner(user) and not self.wfm.can_delete(user):
            return 'Access is denied'
        return ''


    def get_candidate_users(self, for_state=None, privileges='ea', active=None):
        for_state = for_state or self.current_state
        return self.wfm_config.get_candidate_users_for_state(for_state, privileges, active)


    @transaction.atomic
    def delete_with_states(self):
        self.delete_states()
        self.delete()


    def delete_states(self):
        self.states.all().update(previous_state=None, next_state=None)
        self.states.all().delete()



# Injected user properties

def _user_display_str(user):
    return str(user)

# Show username in owner dropdown for change state view
AbstractUser.wfm_display_str_assign = _user_display_str




class InstanceWorkflowManager(object):
    """
    Manages workflow operations for a single WorkflowModel instance.

    Obtained via instance.wfm — do not instantiate directly.

    Permission checks (can_read/can_edit/can_admin) return whether the user
    *could* act based on their groups. Whether they *may* act also depends on
    ownership: only the current owner can edit or admin an object, unless they
    are a global admin.

    Key methods:
    - transition(user, new_state, new_owner, ...)  — perform a state change
    - transition_allowed(...)  — validate without performing (raises on failure)
    - can_read / can_edit / can_admin(user)  — group-based permission checks
    - is_owner(user)  — True if user is the current owner
    - take_ownership / assign / release / reject(user, ...)  — convenience wrappers
    """

    def __init__(self, instance):
        self.instance = instance


    def state_or_error(self):
        """
        Returns instance's current state if defined, otherwise throws error
        """
        if not self.instance.wfm_state:
            raise UnmanagedObject(f"Instance is not managed by workflow: {self.instance}")
        return self.instance.current_state


    def raise_transition_error(self, msg):
        new_msg = f'[{self.instance.get_brief_name()}]: {msg.strip(".")}'
        raise TransitionNotAllowed(new_msg)


    def raise_validation_error(self, msg):
        new_msg = f'[{self.instance.get_brief_name()}]: {msg.strip(".")}'
        raise ValidationError(new_msg)


    def user_permissions(self, user):
        """
        Returns POTENTIAL user permissions for this instance as per config:
        r=read, re=edit, rea=admin
        """
        if not user or not user.is_authenticated:
            return None
        groups = user.groups_set
        state = self.state_or_error()
        conf = state.wfm_state_config()
        if not groups.isdisjoint(set(conf['admin'])):
            return 'rea'
        if not groups.isdisjoint(set(conf['edit'])):
            return 're'
        if not groups.isdisjoint(set(conf['read'])):
            return 'r'
        return ''


    def can_read(self, user):
        """
        Returns True if a given user has read permission on instance
        """
        return 'r' in self.user_permissions(user)


    def can_edit(self, user):
        """
        Returns True if a given user has edit permission on instance, False otherwise.
        Only the owner of a record can actually edit it.
        """
        return 'e' in self.user_permissions(user)


    def can_admin(self, user):
        """
        Returns True if a given user has admin permission on instance.
        Only the owner of a record can actually administer it.

        """
        return 'a' in self.user_permissions(user)


    def is_owner(self, user):
        return self.instance.wfm_state.owner == user


    def can_delete(self, user):
        """
        Must be implemented by derived classes
        Only the owner of a record can actually delete it.
        """
        return False


    def can_take_ownership(self, user):
        """
        To take ownership: acting user must be admin or (user must be editor and current user is null)
        """
        current_state = self.instance.current_state
        try:
            self.instance.wfm.transition_allowed(user, current_state, user)
            return True
        except Exception:
            return False


    def transition_allowed(self, user, new_state, new_owner, suspended=False):
        """
        Checks if a transition is allowed. Raises an exception if not.
        Returns model config if successful.
        """
        new_state = State.phase_str(new_state)
        if not new_state:
            raise TypeError("New state cannot be null or empty")

        if not user:
            self.raise_transition_error("Transition user cannot be null")

        if not user.is_active:
            self.raise_transition_error("Transition user must be active")

        if new_owner and not new_owner.is_active:
            self.raise_transition_error("New owner must be active")


        # Force reload to avoid stale values
        current_state = self.instance.reload_current_state()

        if not current_state:
            # object is not tracked yet.
            # check if user can create the object in new_state
            if user != new_owner:
                self.raise_transition_error("When creating an object, acting user must be owner")
            if suspended:
                self.raise_transition_error("Cannot create an object in a suspended state")
            current_owner = None
            source_state = None
            is_owner = True
        else:
            if current_state.suspended and suspended:
                self.raise_transition_error("Cannot have two consecutive suspended states")
            source_state = current_state.phase
            current_owner = current_state.owner
            if source_state == new_state:
                if new_owner == current_owner:
                    if suspended == current_state.suspended:
                        self.raise_transition_error("Not a transition: same owner(%s) and same state (%s)" %(current_owner,source_state))
            is_owner = (user == current_state.owner)

        config = self.instance.wfm_config

        source_state_config = config.get_state_config(source_state)
        target_state_config = config.get_state_config(new_state)

        #check that user is editor or an admin for this state
        is_admin =  user_in_groups(user, source_state_config['admin'])
        is_editor = user_in_groups(user, source_state_config['edit'])

        # Handle suspension
        if current_state and (suspended != current_state.suspended):
            if source_state != new_state:
                self.raise_transition_error("Cannot change suspension in a transition between two different states")
            if not is_owner:
                if suspended:
                    self.raise_transition_error("Only owner can suspend and object")
                if not is_admin:
                    self.raise_transition_error("Only owner or admins can act on a suspended object")
            return config

        if source_state is None:
            if not is_editor and not is_admin:
                self.raise_transition_error("User must be editor or admin to create a new instance")
        else:
            if source_state != new_state:
                if not is_owner:
                    self.raise_transition_error("User must be owner to change state in a transition")
            elif current_owner:
                if not (is_admin or is_owner):
                    self.raise_transition_error("User must be owner or admin to change owner in a transition")
            else:
                if (user != new_owner) and not (is_admin):
                    self.raise_transition_error("User must be admin to set owner in a transition")

        if current_owner and new_owner and current_owner != new_owner and not current_state.can_delegate:
            self.raise_transition_error(f"User is not allowed to delegate in this state ({source_state})")

        reachable_states = source_state_config['reachable_states']
        if new_state not in reachable_states and new_state != source_state:
            self.raise_transition_error(f"Unreachable state: {new_state} from {source_state}")

        allowed_groups = reachable_states.get(new_state, {}).get('allowed_groups', [])
        if allowed_groups and not user.in_groups(allowed_groups):
            self.raise_transition_error(f"Only users from groups {','.join(allowed_groups)} are allowed to perform this transition")

        #unless not specifified by 'allow_no_owner', the new owner can be none
        allow_release = target_state_config.get('allow_release', 'strict')
        if new_owner is None and allow_release == 'no':
            self.raise_transition_error("The target state does not allow null owner")
        # TODO should check allow_release == 'strict', current_state.transition_type...

        # check that new owner has editing privileges for the target status, otherwise
        # the record will not be editable by its owner
        if new_owner is not None:
            new_owner_is_editor = user_in_groups(new_owner, target_state_config['edit'])
            new_owner_is_admin = user_in_groups(new_owner, target_state_config['admin'])
            if not (new_owner_is_editor or new_owner_is_admin):
                self.raise_transition_error("The new owner for the record would not be able to edit or administer the record")

        # Custom transition validators can raise ValidationError thus aborting the transaction
        self.run_transition_validations(user, current_state, new_state, new_owner, suspended)

        return config


    def run_transition_validations(self, user, current_state, new_state, new_owner, suspended):
        """
        Calls custom transition validators if defined:
        validators can raise ValidationError to prevent the status transition
        """
        current_state = State.phase_str(current_state, 'none')
        self._call_handler_if_exists('validate_state_transition', user, current_state, new_state, new_owner, suspended)
        if current_state != new_state:
            self._call_handler_if_exists(f'validate_any_to_{new_state}', user)
            self._call_handler_if_exists(f'validate_{current_state}_to_any', user)
        self._call_handler_if_exists(f'validate_{current_state}_to_{new_state}', user)


    def _call_handler_if_exists(self, methodname, *args, **kwargs):
        if hasattr(self.instance, methodname):
            method = getattr(self.instance, methodname)
            if callable(method):
                try:
                    method(*args, **kwargs)
                except ValidationError as e:
                    self.raise_validation_error(get_exception_error_msg(e))
                except TransitionNotAllowed as e:
                    self.raise_transition_error(get_exception_error_msg(e))




    @transaction.atomic
    def transition(self, user, new_state, new_owner, message='', suspended=False,
                   force_transition_type=None, impersonated_by=None):
        """
        Performs a transition between two states.
        First, instance is validated (but not saved) through a call to full_clean().
        Transition is validated by 'transition_allowed' method, where all the validation
        logic stands.
        If a previous state exists for the same instance, the 'next_state' attribute is
        set to the new state.
        All the saving operations are performed within a transaction.

        impersonated_by: when set, ``user`` is the impersonated identity and
        ``impersonated_by`` is the real actor (e.g. an admin operating on their behalf).
        """

        # LOCK riga stato corrente, dovrebbe generare istantaneamente un errore se
        # l'oggetto è già bloccato.
        # TODO anche le modifiche dei record diverse dalle transizioni dovrebbero bloccare il record (su POST)
        self.instance.lock_instance()

        new_state = State.phase_str(new_state)

        current_state = self.instance.reload_current_state()
        if current_state != self.instance.current_state:
            raise StaleObject(f'Object {self.instance} has been changed by another transition.')

        # Instance is validated (but not saved)
        # TODO is this the right place to do this?
        try:
            self.instance.full_clean()
        except Exception as e:
            if isinstance(e, (ValidationError, FileNotFoundError)):
                if (user == new_owner) and current_state and (current_state.phase == new_state) and self.can_admin(user):
                    e = None
            if e:
                raise e


        config = self.transition_allowed(user, new_state, new_owner, suspended=suspended)
        next_state = State(instance=self.instance, user=user, phase=new_state, owner=new_owner,
                           message=message, suspended=suspended, impersonated_by=impersonated_by)
        if force_transition_type:
            next_state.transition_type = force_transition_type
        elif current_state and current_state.phase != new_state and config[current_state.phase]['reachable_states'][new_state].get('reject', False):
            next_state.transition_type = 'reject'
        else:
            next_state.transition_type = next_state.get_transition_type(current_state)
        next_state.previous_state = current_state
        next_state.unread = bool(new_owner and (new_owner != user))
        if getattr(settings, 'WORKFLANGO_SNAPSHOT_ENABLED', False):
            source_phase = current_state.phase if current_state else None
            if config[source_phase].get('snapshot', False):
                next_state.snapshot = self.instance.get_workflow_snapshot(new_state)
        next_state.save()

        self.instance.materialize_current_state(next_state)

        if current_state:
            current_state.next_state = next_state
            current_state.unread = False
            current_state.save()

        # An exception in after_state will make the transition fail
        self._call_handler_if_exists('after_state_transition',
                                     previous_state=current_state,
                                     impersonated_by=impersonated_by)
        try:
            transition_done.send(sender=self, instance=self.instance, prev_state=current_state, cur_state=next_state)
        except ValidationError as e:
            self.raise_validation_error(get_exception_error_msg(e))
        except TransitionNotAllowed as e:
            self.raise_transition_error(get_exception_error_msg(e))
        return next_state


    # TODO unused but in tests
    def release(self, user, message=None, impersonated_by=None):
        current_state = self.instance.current_state
        # TODO move this check into transition_allowed()
        if not current_state or not current_state.can_release:
            self.raise_transition_error("Cannot release record")
        return self.transition(user, current_state.phase, None,
                               message=message, impersonated_by=impersonated_by)


    # TODO unused but in tests
    def reject(self, user, message=None, impersonated_by=None):
        current_state = self.instance.current_state
        if current_state:
            reject_to = current_state.get_previous_state()
            if reject_to:
                # Should be current_state.user = reject_to.owner
                return self.transition(user, reject_to.phase, current_state.user,
                                       message=message, impersonated_by=impersonated_by)
        self.raise_transition_error("Cannot reject record")


    # TODO unused but in tests
    def reject_to_state(self, user, state, message=None, impersonated_by=None):
        current_state = self.instance.current_state
        if current_state:
            reject_to = current_state.find_last_state(state)
            if reject_to:
                return self.transition(user, state, reject_to.owner,
                                       message=message, impersonated_by=impersonated_by)
        self.raise_transition_error("Cannot reject record")


    def take_ownership(self, user, message=None, impersonated_by=None):
        cst = self.state_or_error()
        if cst.owner and cst.owner.pk == user.pk:
            return cst
        return self.transition(user, cst.phase, user,
                               suspended=False, message=message, impersonated_by=impersonated_by)


    def assign(self, new_owner, user=None, message=None, impersonated_by=None):
        cst = self.state_or_error()
        user = user or cst.owner
        return self.transition(user, cst.phase, new_owner,
                               suspended=False, message=message, impersonated_by=impersonated_by)


    def get_transition(self, dest_state, user, owner='auto'):
        return WFTransitionDescriptor(self.instance, dest_state, user, owner)


    def get_states(self):
        return self.instance.states.all().order_by('id')


# ---------------------------------------------------------------------------
# User extensions — monkey-patched at import time
#
# workflango adds three helpers to Django's built-in User model:
#   user.groups_list  — sorted list of group names (cached per-instance)
#   user.groups_set   — set of group names (cached per-instance)
#   user.in_groups()  — check membership in one or more groups by name
#
# functools.cached_property cannot be used here: it relies on __set_name__
# being called during class creation, which does not happen when assigning
# a descriptor to an existing class at runtime (monkey-patch).
#
# If your project uses a custom User model, these attributes will still be
# attached to the auth.User class; they have no side-effects on subclasses.
# ---------------------------------------------------------------------------

def _cached_property(method):
    """
    Property descriptor that caches its result on first access.

    functools.cached_property cannot be used here because it sets self.attrname
    via __set_name__, which Python only calls during class body execution — not
    when a descriptor is assigned to an existing class at runtime. Without
    attrname, its __get__ raises TypeError. This minimal replacement stores the
    cached value under a mangled name (_<method>) directly on the instance dict.
    """
    attr = f'_{method.__name__}'
    def wrapper(self):
        if not hasattr(self, attr):
            setattr(self, attr, method(self))
        return getattr(self, attr)
    return property(wrapper)


def _user_in_groups(user, *groups):
    for group in groups:
        if isinstance(group, str):
            group = [grp.strip() for grp in group.split(',')]
        elif isinstance(group, int):
            group = [group]
        for grp in group:
            if grp in user.groups_list:
                return True
    return False
AbstractUser.in_groups = _user_in_groups

def _user_groups_list(user):
    return sorted(list(set(user.groups.all().values_list('name', flat=True))))
AbstractUser.groups_list = _cached_property(_user_groups_list)

def _user_groups_set(user):
    return set(user.groups_list)
AbstractUser.groups_set = _cached_property(_user_groups_set)

