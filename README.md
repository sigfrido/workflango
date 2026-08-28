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
- `ChangeStateView` / `ObjectHistoryView` — ready-to-mount views for a traditional (non-DRF) Django GUI, with shipped, i18n-ready templates
- Full Django i18n support for the library's own GUI chrome, with a bundled Italian translation catalog
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

## Django GUI (traditional views)

Unlike sibling project [drf-sebastian](https://github.com/sigfrido/drf-sebastian) (a DRF-driven auto-GUI with field-level permissions), workflango has no opinion on your page layout or CRUD forms — it ships the workflow-specific pieces only: the change-state confirmation screen, the history table, and a handful of template fragments (buttons, edit-button, unread indicator) meant to be `{% include %}`d into your own list/detail templates.

```python
# models.py
class MyDocument(WorkflowModel):
    ...
    # view_base_name defaults to the lowercased class name ('mydocument');
    # override it as a plain class attribute to pick a different URL prefix.

# urls.py -- these four names are the whole convention:
path('documents/', MyDocumentListView.as_view(), name='mydocument_list')
path('documents/<int:pk>/', MyDocumentDetailView.as_view(), name='mydocument_detail')
path('documents/<int:pk>/edit/', MyDocumentUpdateView.as_view(), name='mydocument_edit')
path('documents/<int:pk>/history/', ObjectHistoryView.as_view(model=MyDocument), name='mydocument_history')
path('documents/<int:pk>/change-state/<str:nuovo_stato>/', ChangeStateView.as_view(model=MyDocument), name='mydocument_change_state')
```

Every `WorkflowModel` instance then exposes `get_absolute_url()`, `get_edit_url()`, `get_history_url()`, and `get_change_state_url(destination)` built from that same `view_base_name` — the shipped templates (and `GUITestMixin`'s `get_detail_view()`/`get_history_view()`/`get_change_state_view()` helpers) rely on nothing else.

Mix `WorkflowModelList` / `WorkflowDetailMixin` / `WorkflowModelCreate` / `WorkflowModelUpdate` into your own `ListView`/`DetailView`/`CreateView`/`UpdateView`, then in your templates:

```django
{% include "workflango/django/workflow_edit_btn.html" %}
{% include "workflango/django/workflow_state_detail.html" %}   {# a <tr> for a properties table #}
{% include "workflango/django/workflow_buttons.html" %}        {# take ownership / transition / reject / release / suspend #}
```

See `testproject/` (in the repository, not the installed package) for a complete working example: two models, four views each, a base template, and a standard Django login page — no REST framework, no JS framework, plain `<select>` dropdowns for FK fields.

## Internationalization (i18n)

The library's own GUI chrome (buttons, the change-state form, the history table, access-denied messages, ...) is fully translatable and ships an Italian catalog out of the box. Every library-owned string carries the translation context `"workflango"`, so it can never be silently shadowed by another installed app's plain-context catalog defining the same English word (`django.contrib.admin` ships its own translations for "Save", "Delete", ...).

Nothing to configure beyond Django's own `USE_I18N` / `LANGUAGE_CODE` — set `LANGUAGE_CODE = 'it'` (or activate Italian per-request via `django.middleware.locale.LocaleMiddleware`) and the shipped chrome renders in Italian automatically.

Maintainer workflow for anyone extending the library's own GUI chrome: use `wgettext()` (Python, `workflango/i18n.py`) or `{% wtrans %}` (templates, `workflango/templatetags/workflow_tags.py`) instead of calling `pgettext()` directly — both are thin wrappers around the `"workflango"` context so the literal context string only needs to be typed once. `django-admin makemessages` cannot see through either wrapper (it only recognizes literal `pgettext()`/`pgettext_lazy()` calls), so `workflango/_translatable_strings.py` exists purely as an extraction registry: add a matching `pgettext('workflango', "...")` line there for every new `wgettext()`/`{% wtrans %}` call, then regenerate the catalog from `workflango/`:

```
django-admin makemessages -l it --no-location
django-admin compilemessages
```

`workflow_defaults`/module-level dicts and tuples evaluated once at import time (e.g. form field `choices`) must use `wgettext_lazy()` instead of `wgettext()`, or the translation gets baked in at whatever language was active during process startup instead of the requesting user's language.

## Impersonation

Allows one user to perform transitions on behalf of another. The real actor is recorded in `State.impersonated_by`; `State.user` holds the impersonated identity. **workflango does not decide who may impersonate whom** — that's entirely an application concern (see below); the engine only records and, since `1.0.0rc1`, enforces an explicit hand-off (see "Ownership and impersonation" below).

Enable globally in settings:

```python
WORKFLANGO_ALLOW_IMPERSONATE = True
```

`WorkflowConfig.get_impersonable_users(user)` is the policy hook consulted by the DRF layer's `resolve_acting_user()`. Its **default** — superusers and `WORKFLOW_ADMIN_GROUP` members may impersonate any active user — is only a default, not a rule the engine enforces elsewhere; override it per workflow with any policy that fits your app:

```python
MyDocument.configure_workflow(
    config=...,
    impersonable_users=lambda user: Delegation.active_delegates_for(user),
)
```

This is symmetric, not just "admin down to regular user": a temporary-delegation policy (a manager delegates to a specific subordinate while on leave, via a `Delegation` model like the sketch above) is just as valid a use of the same mechanism. Nothing about `is_owner()`, `transition_allowed()`, or the `impersonate`/`reclaim` transition types below cares whether the impersonator happens to be a workflow "admin" for the relevant state — group-based admin rights and impersonation authorization are unrelated axes.

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

For a GUI (non-DRF) consumer, the contract is: middleware swaps `request.user` to the impersonated target for the rest of the request and stashes the real actor on `request.impersonated_by` — `_BaseWorkflowTransitionMixin.check_and_transition()` and every other ownership check in the library already read both attributes this way. `testproject/demo/middleware.py`'s `ImpersonateMiddleware` is a complete, runnable example (superuser-only, session-based) — one way to wire the contract up, not the only one.

### Ownership and impersonation

`state.owner == user` alone does not mean `user` is really acting: an admin impersonating userx would satisfy that comparison exactly as if they *were* userx, with no distinction and no forced audit trail. `State.owned_by(user, impersonated_by=None)` is the real check — it requires **both** the owner match **and** an impersonation-context match against what's already recorded on the state:

```python
state.owned_by(user, impersonated_by)  # == state.owner == user and state.impersonated_by == impersonated_by
```

`InstanceWorkflowManager.is_owner()` (and everything gated by it — plain field edits via `WorkflowModelUpdate`, `wf_editable`, phase-changing transitions, ...) goes through this. Practically: an admin impersonating userx on a record userx genuinely owns must explicitly call `take_ownership(userx, impersonated_by=admin)` — a real, audited `transition()` — before `is_owner()`-gated actions succeed; userx is symmetrically locked out until they call `take_ownership(userx)` (with no `impersonated_by`) to reclaim it back. This works purely by identity (`user == new_owner == current_owner`, see `transition_allowed()`), not by group membership, so it doesn't matter whether the impersonated target is a workflow "admin" for the state or not. A *different*, separately-authorized impersonator can also take over an existing claim the same way (workflango doesn't track which impersonator "owns" the impersonation itself, only which identity currently holds the record) — each claim is independently audited via `State.impersonated_by`.

Two transition types make this explicit in the history (`State.transition_type`, shown by `transition_type_display()`): **`impersonate`** — same owner/user as the previous state, but `impersonated_by` is now set and differs from what the previous state recorded (covers both a first claim and a hand-off between two different impersonators) — and **`reclaim`** — same owner/user, but `impersonated_by` is now cleared, i.e. the genuine owner took it back.

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

Using [drf-sebastian](https://github.com/sigfrido/drf-sebastian) as your GUI layer? `workflango.contrib.sebastian` is an optional module — never imported by core workflango — that adds the GUI-aware behavior sebastian's `GUIMixin`/renderer/router expect (a list-badge column, `template_namespace`, `can_update`/`can_delete`, the `history`/`change_state_form` actions) as drop-in replacements for the mixins above. See [docs/sebastian-integration.md](docs/sebastian-integration.md).

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

## Demo project

`testproject/` (repository only, not part of the installed package) is a small, traditional Django project — plain class-based views, no REST framework — demonstrating workflango driving two related models with group-based permissions instead of sebastian's field-level ones:

- **Supplier**: `proposed` → `active` → `archived`. Any authenticated user proposes a supplier; only a manager can activate or archive it.
- **Request**: `draft` → `submitted` → `approved` / `rejected`, and can only target an *active* supplier (enforced both in the form's queryset and as a `Request.clean()` integrity check). Which fields render as editable inputs vs. read-only text in the edit form depends on the request's current phase (`Request.EDITABLE_FIELDS_BY_PHASE`) — workflango has no field-level permission system of its own, so this is a template-level pattern specific to the demo, not a library feature.

It also demonstrates a GUI on top of the library's [impersonation](#impersonation) feature (superuser-only): `demo/middleware.py`'s `ImpersonateMiddleware` swaps `request.user` for a session-selected target and stashes the real admin on `request.impersonated_by`, which is exactly the contract `_BaseWorkflowTransitionMixin.check_and_transition()` already expects — no changes needed anywhere else for `impersonated_by` to show up correctly on transitions performed while impersonating. `demo/views.py`'s `ImpersonateStartView`/`ImpersonateStopView` are demo-only, ad hoc views (not part of the library, by design — workflango only ships the request-level contract, not a GUI for driving it).

```
cd testproject
python manage.py migrate
python manage.py create_demo_data   # groups + demo accounts, see table below
python manage.py runserver
```

| Username | Group | Password |
|----------|-------|----------|
| `admin` | superuser | `demo12345` |
| `manager1` | MANAGERS | `demo12345` |
| `user1` | USERS | `demo12345` |

Its base template vendors Bootstrap (`testproject/static/vendor/bootstrap/`, copied from drf-sebastian's own vendored copy) for basic styling only — no Tom Select, no htmx, no icon font; FK fields are plain `<select>` dropdowns and the login page is `django.contrib.auth.views.LoginView` with a bare-bones template.

## Running tests

```
python manage.py test tests              # the engine itself
cd testproject && python manage.py test demo   # the demo's GUI/workflow smoke tests
```

## API reference

Full API reference generated with [pdoc](https://pdoc.dev) lives in `docs/api/` (open `docs/api/index.html`). Regenerate it after any docstring change:

```
pip install -e ".[dev]"
python tools/gen-docs.py
```
