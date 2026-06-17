# workflango

A reusable Django BPM workflow engine.

Manages state transitions for any Django model: permissions by group, full transition history, atomic locking, signals, and pluggable validation hooks.

## Features

- `WorkflowModel` abstract base — attach workflow to any model with a single inheritance
- State machine defined declaratively per model (`configure_workflow`)
- Group-based permissions per state (read / edit / admin)
- Full transition history as a linked-list of `State` records
- Atomic transitions with `SELECT FOR UPDATE [NOWAIT]` where supported by DB backend
- `transition_done` signal for downstream reactions
- Impersonation — admin or delegate acts on behalf of another user, recorded in `State.impersonated_by`
- Snapshot — JSON copy of the object saved on each transition for audit/rollback, with custom serializers
- DRF integration — serializers, viewset mixin, and filter backend out of the box
- Generic views and CBV mixins (`WorkflowModelCreate/Update/List/Detail`)
- Management commands: `init_wf_groups`, `check_wf_config`, `check_wf_objects`
- Test mixins (`WorkflowTestMixin`, `GUITestMixin`) for consumer apps

## Requirements

- Python >= 3.10
- Django >= 4.2 (tested on 4.2 LTS, 5.x, 6.x)

Database support for atomic locking (`SELECT FOR UPDATE`):

| Backend | Lock behaviour |
|---------|----------------|
| PostgreSQL | `NOWAIT` — fails immediately if row is already locked (recommended) |
| MySQL 8.0+ / MariaDB 10.3+ | `NOWAIT` — same as PostgreSQL |
| MySQL < 8.0 / MariaDB < 10.3 | blocking `FOR UPDATE` — waits; no instant failure |
| SQLite | no-op — locking silently skipped; safe for single-process use and tests |

## Installation

```
pip install workflango
```

For local development alongside a consumer project:

```
pip install -e ../workflango
```

## Quick start

```python
# models.py
from workflango.models import WorkflowModel

class MyDocument(WorkflowModel):
    title = models.CharField(max_length=200)

MyDocument.configure_workflow(
    config=(
        (None, {'reachable_states': {'draft': {}}}),
        ('draft', {
            'reachable_states': {'published': {'caption': 'Publish', 'owner_mode': 'none'}},
            'read': ['EDITORS'], 'edit': ['EDITORS'], 'admin': ['ADMINS'],
            'is_closed': False,
        }),
        ('published', {'is_closed': True, 'reachable_states': {}}),
    ),
    defaults={'read': ['EDITORS'], 'edit': ['EDITORS'], 'admin': ['ADMINS']},
)
```

```python
# First transition (attaches object to workflow)
doc = MyDocument.objects.create(title='Hello')
doc.wfm.transition(request.user, 'draft', request.user)

# Subsequent transitions
doc.wfm.transition(request.user, 'published', None)
```

## Impersonation

Allows an admin (or delegate) to perform transitions on behalf of another user. The real actor is recorded in `State.impersonated_by`; `State.user` holds the impersonated identity.

Enable globally in settings:

```python
WORKFLANGO_ALLOW_IMPERSONATE = True
```

By default, superusers and members of `WORKFLOW_ADMIN_GROUP` can impersonate any active user. Override per workflow:

```python
MyDocument.configure_workflow(
    config=...,
    impersonable_users=lambda user: Delegation.active_delegates_for(user),
)
```

Programmatic use:

```python
# Admin (real_user) acts as target_user
state = doc.wfm.transition(target_user, 'published', None, impersonated_by=real_user)
assert state.user == target_user
assert state.impersonated_by == real_user

# Who can real_user impersonate?
qs = MyDocument.wfm_config.get_impersonable_users(real_user)
```

In the DRF API, pass `"user": <id>` in the `change_state` POST body to act as that user; use `?as_user=<id>` on GET endpoints to scope list results.

## Snapshot

Saves a JSON copy of the object at each transition for audit or rollback inspection.

Enable globally:

```python
WORKFLANGO_SNAPSHOT_ENABLED = True
```

Enable per state (snapshot is taken when leaving that state):

```python
MyDocument.configure_workflow(
    config=(
        ('draft', {
            'snapshot': True,           # snapshot on every exit from 'draft'
            'reachable_states': {'published': {}},
            ...
        }),
        ...
    ),
    snapshot_serializer=MyDocumentSerializer,   # DRF serializer used by default
)
```

`State.snapshot` is then a plain `dict` (JSON-serialisable). Override the method for custom logic:

```python
class MyDocument(WorkflowModel):
    def get_workflow_snapshot(self, new_phase):
        data = MyDocumentSerializer(self).data
        data.pop('internal_notes', None)    # strip sensitive fields
        return dict(data)
```

## DRF integration

Install `djangorestframework` alongside workflango, then:

```python
# serializers.py
from workflango.drf import WorkflowSerializerMixin

class MyDocumentSerializer(WorkflowSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = MyDocument
        fields = ['id', 'title', 'current_state']   # current_state added by mixin

# views.py
from workflango.drf import WorkflowViewSetMixin, WorkflowFilterBackend

class MyDocumentViewSet(WorkflowViewSetMixin, ModelViewSet):
    queryset = MyDocument.objects.all()
    serializer_class = MyDocumentSerializer
    filter_backends = [WorkflowFilterBackend]

    def get_queryset(self):
        acting_user, _ = self.get_effective_user(self.request)
        return MyDocument.objects.filter(wfm_state__owner=acting_user)
```

Actions added automatically:

| Method | URL | Description |
|--------|-----|-------------|
| GET | `/{pk}/workflow_history/` | Full transition history |
| POST | `/{pk}/change_state/` | Perform a transition |
| POST | `/{pk}/mark_read/` | Set or clear the `unread` flag (owner only) |

`mark_read` POST body (all fields optional):

```json
{"read": true}
```

Returns `{"unread": false}`. Defaults to `read: true` if body is omitted (auto-mark-read on page open). Pass `{"read": false}` to toggle back to unread. Only the current owner can call this endpoint.

`change_state` POST body:

```json
{
    "phase": "published",
    "owner": 42,
    "user": 15,
    "message": "Approved",
    "suspended": false
}
```

## Settings

```python
WORKFLOW_USERS_GROUPS = (
    ('EDITORS', 'Content editors'),
    ('ADMINS', 'Workflow administrators'),
)
WORKFLOW_ADMIN = 'admin'
WORKFLOW_ADMIN_GROUP = 'ADMINS'
WORKFLOW_TRANS_MSG_MAX_LEN = 4096           # optional

# Impersonation
WORKFLANGO_ALLOW_IMPERSONATE = False        # default: disabled

# Snapshot
WORKFLANGO_SNAPSHOT_ENABLED = False         # default: disabled

# Optional overrides
WORKFLANGO_ACCESS_DENIED_URL = '/forbidden/'        # default: '/'
WORKFLANGO_NOTIFY_FUNC = 'myapp.utils.notify_admins'  # default: Django mail_admins
```

## Running tests

```
python manage.py test tests
```
