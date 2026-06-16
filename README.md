# workflango

A reusable Django BPM workflow engine.

Manages state transitions for any Django model: permissions by group, full transition history, atomic locking, signals, and pluggable validation hooks.

## Features

- `WorkflowModel` abstract base — attach workflow to any model with a single inheritance
- State machine defined declaratively per model (`configure_workflow`)
- Group-based permissions per state (read / edit / admin)
- Full transition history as a linked-list of `State` records
- Atomic transitions with PostgreSQL `SELECT FOR UPDATE NOWAIT`
- `transition_done` signal for downstream reactions
- Generic views and CBV mixins (`WorkflowModelCreate/Update/List/Detail`)
- Management commands: `init_wf_groups`, `check_wf_config`, `check_wf_objects`
- Test mixins (`WorkflowTestMixin`, `GUITestMixin`) for consumer apps

## Requirements

- Python >= 3.10
- Django >= 4.2 (tested on 4.2 LTS, 5.x, 6.x)
- PostgreSQL recommended (SQLite supported for tests)

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

## Settings

```python
WORKFLOW_USERS_GROUPS = (
    ('EDITORS', 'Content editors'),
    ('ADMINS', 'Workflow administrators'),
)
WORKFLOW_ADMIN = 'admin'
WORKFLOW_ADMIN_GROUP = 'ADMINS'
WORKFLOW_TRANS_MSG_MAX_LEN = 4096  # optional

# Optional overrides
WORKFLANGO_ACCESS_DENIED_URL = '/forbidden/'  # default: '/'
WORKFLANGO_NOTIFY_FUNC = 'myapp.utils.notify_admins'  # default: Django mail_admins
```

## Running tests

```
python manage.py test tests
```
