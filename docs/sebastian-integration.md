# Integrating workflango with drf-sebastian

`workflango.drf` (the core DRF integration — `WorkflowSerializerMixin`,
`WorkflowViewSetMixin`, `StateSerializer`, impersonation resolution, the
`workflow_history`/`change_state`/`mark_read` actions) has no opinion on GUI
rendering and no dependency on [drf-sebastian](https://github.com/sigfrido/drf-sebastian)
— same philosophy as the plain-CBV templates (see README.md's "Django GUI" section).

If your project uses drf-sebastian as its GUI layer, `workflango.contrib.sebastian`
is an **optional** module that adds the GUI-aware behavior sebastian's `GUIMixin` /
renderer / router expect by naming convention — a list-view badge column, the
`__can_update` flag, `template_namespace`, `can_update`/`can_delete`,
`get_workflow_transitions`, and the `history`/`change_state_form` GUI actions. It is
never imported by any core workflango module: importing it is the opt-in.

## Prerequisites

Both `djangorestframework` and `drf-sebastian` installed and configured in the
consuming project. `drf-sebastian` is not published on PyPI — install it from its own
repository. Importing `workflango.contrib.sebastian` without it installed raises a
clear `ImportError` telling you so, rather than failing obscurely.

## Usage

```python
# serializers.py
from workflango.contrib.sebastian import SebastianWorkflowSerializerMixin

class MyModelSerializer(SebastianWorkflowSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = MyModel
        fields = ['id', 'title', 'current_state']
    class Sebastian:
        list_fields = ['title', 'current_state_for_list']

# views.py
from sebastian.mixins import GUIMixin
from workflango.drf import WorkflowFilterBackend
from workflango.contrib.sebastian import SebastianWorkflowViewSetMixin

class MyModelViewSet(SebastianWorkflowViewSetMixin, GUIMixin, viewsets.ModelViewSet):
    queryset = MyModel.objects.all()
    serializer_class = MyModelSerializer
    filter_backends = [WorkflowFilterBackend]
```

`SebastianWorkflowSerializerMixin`/`SebastianWorkflowViewSetMixin` are drop-in
replacements for `workflango.drf`'s plain `WorkflowSerializerMixin`/`WorkflowViewSetMixin`
— they already extend them, so you don't compose both. Place
`SebastianWorkflowViewSetMixin` before sebastian's `GUIMixin` in the MRO so its
`can_update`/`can_delete` override `GUIMixin`'s defaults.

## What it adds

| On `SebastianWorkflowSerializerMixin` | Purpose |
|---|---|
| `current_state_for_list` | `@gui_field`-decorated HTML badge column (phase, owner, date, suspended/message icons) for `Sebastian.list_fields`. Never in the JSON API response. |
| `to_representation()` override | Adds `__can_update` to the payload when `request.sebastian_gui` is set, so list/detail templates know whether to show an edit link — impersonation-aware via `State.owned_by()`. |

| On `SebastianWorkflowViewSetMixin` | Purpose |
|---|---|
| `template_namespace = 'workflango'` | Tells sebastian's renderer to resolve templates from `workflango/sebastian/{pack}/...` before falling back to `sebastian/{pack}/...` — see the four fragments shipped at `workflango/templates/workflango/sebastian/htmx/{list,detail,confirm,history}.html`. |
| `can_update()` / `can_delete()` | GUI permission hooks read by sebastian's `GUIMixin` — impersonation-aware ownership check; deletion always disabled. |
| `get_workflow_transitions()` | Duck-typed hook sebastian's renderer calls to inject `workflow_transitions` into the template context, driving the transition action buttons in `detail.html`. |
| `history` action | GUI-flavored alias of `workflow_history`, with a `.gui_config` dict so sebastian's router surfaces it as a button. |
| `change_state_form` action | GET renders the inline confirmation form (`confirm.html`); POST performs the transition and returns updated detail data for an htmx swap. Uses `WorkflowActionSerializer` (also in this module) as its schema. |

Everything else — `StateSerializer`, `check_wf_permission()`, impersonation
resolution (`resolve_acting_user`/`get_effective_user`/`get_impersonable_users`), and
the `workflow_history`/`change_state`/`mark_read` actions — comes from the base
`workflango.drf` mixins these subclass; use them as documented in README.md's "DRF
integration" section.

## Templates

Already shipped at `workflango/templates/workflango/sebastian/htmx/`:
`list.html` (a one-line `{% extends 'sebastian/htmx/list.html' %}`), `detail.html`
(workflow status card + transition buttons), `confirm.html` (the inline confirm form),
`history.html` (the full-page state history table). Override any of them in your own
app under the same relative path if you need different markup — Django's app-loader
resolution order (your app before `workflango`) takes care of the rest.
