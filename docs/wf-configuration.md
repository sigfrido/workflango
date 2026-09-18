# Workflow configuration reference

Full reference for every key recognized by `WorkflowModel.configure_workflow()` and
the `WorkflowConfig` dict it builds. This is a reference, not a tutorial — see
README.md's "Quick start" for a walkthrough. Come here when you need to know what a
specific key does or what values it accepts.

```python
MyModel.configure_workflow(
    config=(...),               # see "1. Phase-level keys" / "2. Transition-level keys"
    defaults={...},             # merged into every phase's config, see below
    impersonable_users=...,     # see "0. configure_workflow() kwargs"
    snapshot_serializer=...,    # see "0. configure_workflow() kwargs"
)
```

`config`/`defaults` fall back to the class attributes `workflow_phases`/`workflow_defaults`
if omitted — `configure_workflow()` is a no-op if the model is already configured.

## 0. `configure_workflow()` kwargs

| kwarg | Type | Default | What it does |
|---|---|---|---|
| `config` | a `tuple` — every other shape raises `InvalidWorkflowConfiguration` | falls back to the class attribute `workflow_phases` | The full phase table. Each **element** of the tuple describes one phase, and may be either a `(phase_name, dict)` pair or a `dict` that includes its own `'name'` key (the two are interchangeable — mixing styles within the same `config` is fine). `None` as `phase_name`/`'name'` defines the entry point (the phase an object is created into). |
| `defaults` | `dict` | falls back to `workflow_defaults`, else `{}` | Deep-copied as the starting point for every phase's config before that phase's own keys are applied on top. This is where shared `read`/`edit`/`admin`/`properties` normally live, so individual phases only need to override what differs. |
| `impersonable_users` | `callable(user) -> queryset` | `None` | Overrides the default impersonation policy (superusers / `WF_ADMIN_GROUP` members may impersonate any active user). See README.md "Impersonation". |
| `snapshot_serializer` | a DRF `Serializer` class | `None` | Used by `get_workflow_snapshot()` to serialize the instance when a snapshot is taken (see the phase-level `snapshot` key below). |

`impersonable_users(user)` is always evaluated against the real, originally-authenticated
caller of the request, never against an already-impersonated identity — the DRF layer's
`resolve_acting_user()` enforces this anti-chaining invariant regardless of how many
layers reassign `request.user` upstream (e.g. a GUI's session-swap middleware sitting in
front of a DRF endpoint). See README.md "API authorization and anti-chaining" for the
full explanation and a worked example (a single API service-account user, e.g. `hr_app`,
either granted `impersonable_users` rights over an entire office, or used purely as an
entry point that delegates via normal workflow ownership hand-off instead of impersonation).

Related Django settings that gate config-driven behavior, but aren't `configure_workflow()`
kwargs themselves:

| Setting | Affects |
|---|---|
| `WF_SNAPSHOT_ENABLED` (bool, default `False`) | Global on/off switch for the per-phase `snapshot` key — see below. |
| `WF_ADMIN` / `WF_ADMIN_GROUP` | `WorkflowConfig.admin()`/`is_admin()` — independent of any phase's own `admin` group list. |
| `WF_USERS_GROUPS` | Every group name used in a phase's `read`/`edit`/`admin` lists must be listed here, or `check_defined_groups()` raises `InvalidWorkflowConfiguration`. Declaring a group here does **not** create it — see below. |
| `WF_ACCESS_DENIED_URL` | Fallback redirect target — unrelated to phase config, listed here only because it's easy to conflate with the above. |

`WF_USERS_GROUPS` only declares which group names are *valid* — the actual Django
`Group` rows are created by the `init_wf_groups` management command
(`init_all_groups()` in `workflango/user_groups.py`, idempotent — safe to re-run).
When initializing a fresh environment (e.g. a new container), run it after both
`migrate` (the `Group` table must already exist) and `check_wf_config` (fail fast on
a broken config before bothering to create groups for it):

```
manage.py migrate
manage.py check_wf_config
manage.py init_wf_groups
```

## 1. Phase-level keys

These go in the second element of each `(phase_name, {...})` pair in `config=`
(the dict itself, one per phase):

```python
config=(
    (None, {'reachable_phases': {'draft': {}}}),
    ('draft', {
        'reachable_phases': {'published': {}},
        'read': ['EDITORS'], 'edit': ['EDITORS'], 'admin': ['ADMINS'],
        'is_closed': False,
        'properties': {'edit_button_label': 'Edit'},
    }),
    ...
)
```

| Key | Type | Default | What it controls |
|---|---|---|---|
| `read` | `list[str]` (group names) | **none** — must be supplied by the phase or `defaults`, or accessing it raises `KeyError`/`InvalidPhase` | Groups granted read permission on instances in this phase. |
| `edit` | `list[str]` (group names) | **none**, same as `read` | Groups granted edit permission. Checked on the *source* phase for the acting user, and on the *target* phase for the new owner (who must be editor or admin there, or the transition is refused). |
| `admin` | `list[str]` (group names) | **none**, same as `read` | Groups granted admin permission — a superset of edit rights (e.g. can release/delegate regardless of `allow_release`/`allow_delegate`). Checked on both source and target phase during a transition. |
| `is_closed` | `bool` | `False` | Marks a phase as terminal. Used to filter phase lists (`get_phases_list(closed=True/False)`) and by `State.is_closed()`. Purely informational — does **not** itself block transitions (`reachable_phases` does that). |
| `snapshot` | `bool` | `False` | When `True` **and** `settings.WF_SNAPSHOT_ENABLED` is `True`, leaving this phase calls `instance.get_workflow_snapshot(new_phase)` and stores the result on the new `State.snapshot` JSON field. Evaluated on the phase being **left**, not the one being entered. |
| `allow_release` | `str`, one of `'no'` / `'always'` / `'strict'` | `'strict'` | Whether the owner may release (set owner to `None`). `'no'`: never releasable — any transition into this phase with `new_owner=None` is refused. `'always'`: always releasable. `'strict'`: releasable unless the current state's `transition_type` is `delegate`/`assign`/`change_assign`/`reassign` (i.e. must first be "taken" before it can be released). Admins can always release regardless of this setting. Validated — see §4. |
| `allow_delegate` | `str`, one of `'no'` / `'yes'` | `'yes'` | Whether the current owner may delegate (hand off to a different, explicit owner) while in this phase. `'no'` blocks delegation unless the owner is also an admin. Validated — see §4. |
| `properties` | `dict` (arbitrary) | `{}` | Free-form metadata bag for the phase — see §3. Merges (shallow) with `defaults['properties']`: the phase's own keys override same-named default keys, the rest of the default dict's keys pass through unchanged. |
| `reachable_phases` | `dict[str, dict]` — maps destination-phase-name → transition config | `{}` | Which phases are reachable from this one, and the per-transition config for each — see §2. |

Any other top-level key in a phase's dict is copied through as-is and is **not**
read by the engine itself — a place to stash app-specific metadata if you need one,
at your own risk of a future workflango release using the same name.

### Auto-generated reject transitions

For every forward transition `A → B` you declare, workflango automatically adds a
reciprocal reject transition `B → A` (with `{'reject': True}`) to `B`'s own
`reachable_phases`, **unless**:
- the transition config for `A → B` sets `'allow-reject': False` (note: transition-level
  key, hyphenated — see §2), or
- `B`'s `reachable_phases` already explicitly defines its own transition back to `A`.

This is why a typical "approve / reject" workflow only needs to declare the forward
`draft → submitted → approved` chain — the "reject back to draft" transitions appear
for free unless you opt out.

## 2. Transition-level keys

These go inside a specific destination's config, i.e. `reachable_phases[dest_phase]`:

```python
'reachable_phases': {
    'published': {
        'caption': 'Publish',
        'owner_mode': 'none',
        'allowed_groups': ['EDITORS_SENIOR'],
        'require_message': True,
    },
},
```

**Any value here may be a plain literal, or a `callable(transition_descriptor) -> value`**,
resolved lazily when the transition is inspected (the callable receives the
`WFTransitionDescriptor` instance as its only argument).

| Key | Type | Default | What it controls |
|---|---|---|---|
| `allow-reject` (hyphen, not underscore) | `bool` | `True` | Only meaningful on a forward transition's own config. Set `False` to suppress the automatic reciprocal reject transition described above. |
| `reject` | `bool` | `False` (usually set automatically, see above — rarely set by hand) | Marks this transition as a "send back" transition. Affects: owner auto-guessing (defaults to the last owner of the destination phase), the default `require_message` (`True` for reject transitions), the default caption ("Send back to …"), button styling, and forces `State.transition_type = 'reject'` when executed. |
| `caption` | `str` (or callable) | Falls back to a built-in, translated caption depending on the command (Take ownership / Release / Suspend / Resume / Delegate / Assign / "Send back to …" / "Go to: …") | The button/link label rendered by the shipped templates. |
| `owner_mode` | `str`, informally one of `'none'` / `'user'` / `'last_owner'` / `'assign'` / `'assign-optional'` | `'none'` | How the new owner is auto-selected when no owner is explicitly supplied: `'none'` → unassigned, `'user'` → the acting user, `'last_owner'` → whoever last owned this phase, `'assign'`/`'assign-optional'` → show an owner picker in the transition form (the `-optional` variant allows leaving it empty). **Not validated** against this set — an unrecognized value silently behaves like `'none'`. |
| `allowed_groups` | `list[str]` (group names) | `[]` | Restricts who may perform *this specific* transition, beyond the normal edit/admin/ownership checks. Enforced server-side (the transition is refused if the acting user isn't in one of these groups) and used client-side to disable the button. |
| `hidden` | `bool` (or callable) | `None` | UI-only hint to hide the transition button entirely. **Not enforced server-side** — hiding a button doesn't block the transition if requested directly. |
| `disabled` | `bool` (or callable) | `None` | UI-only hint to render the button disabled/greyed-out. Also **not enforced server-side** beyond whatever `allowed_groups` already restricts. |
| `require_message` | `bool` (or callable) | Computed: `True` if this is a reject transition, or the command is `delegate`/`reject`/`release`/`suspend`, or the command is `take-ownership`/`assign` and there's a pre-existing different owner; `False` otherwise | Whether the transition confirmation form requires a non-empty message. |
| `default_owner` | a user instance (or callable returning one) | `None` → falls back to the last owner of the destination phase | Pre-selected owner offered in the owner-picker for the transition form. |

Since `hidden`/`disabled` are UI-only, never rely on them as an access-control
mechanism by themselves — always pair them with `allowed_groups` (or the phase-level
`read`/`edit`/`admin` groups) for anything that actually needs to be enforced.

## 3. `properties`-level keys

These go inside a phase's own `properties` dict (§1). Unlike the keys above,
`properties` is mostly a free-form bag for your own application — workflango itself
only reads these four:

| Key | Type | Default | What it controls |
|---|---|---|---|
| `edit_button_label` | `str` | `None` (renders as an empty label) | Label of the "Edit" button on the detail view (shipped `workflow_edit_btn.html` template). Only relevant while the object is editable. |
| `description` | `str` | `None` | The *destination* phase's `description` is rendered as the tooltip (`title=` attribute) on each transition button in the shipped `workflow_buttons.html` template. The *current* phase's `description` isn't rendered by any shipped template, but is available to host applications via `transition.phase_description`. |
| `help_topic` | `str` | `None` | Not rendered by any shipped template — an extension point for host applications wanting contextual help links, available via `transition.phase_help_topic` / `transition.destination_help_topic()`. |
| `disable_editing` | `bool` | `None`/falsy | When truthy, forces the object to read-only in `WorkflowDetailMixin`'s context (`wf_editable = False`) regardless of ownership — lets a phase declare itself non-editable even to its current owner. |

Any other key inside `properties` is never read by workflango itself — put whatever
your own templates/views need there. `testproject/demo/models.py`'s `editable_fields`
(consumed by `SupplierForm`/`RequestForm` to decide which fields render as inputs vs.
read-only text per phase) is a real, worked example of this pattern.

## 4. Validation

`WorkflowConfig.check()` is **not** run automatically — `configure_workflow()` never
calls it. Run it explicitly via `manage.py check_wf_config` (see the initialization
sequence above), typically in CI or right after deploying a config change, since a
broken config otherwise only surfaces the first time some code path happens to hit
the specific problem.

`check()` validates:

- Every phase is reachable from `None` (via `reachable_phases`).
- Every group name used in a phase's `read`/`edit`/`admin` is declared in `settings.WF_USERS_GROUPS`.
- At least one non-`None` phase has `is_closed: True` — otherwise an instance could
  never reach a final state, which is virtually always a configuration mistake.
- `allow_release`/`allow_delegate` are set to one of their allowed values:

| Key | Default | Allowed values |
|---|---|---|
| `allow_release` | `'strict'` | `'no'`, `'always'`, `'strict'` |
| `allow_delegate` | `'yes'` | `'no'`, `'yes'` |

Any other value for these two keys raises `InvalidWorkflowConfiguration`. Note that
`owner_mode` (§2) is **not** validated despite being effectively constrained to a
fixed set of values by the code that consumes it — a typo there fails silently
(falls back to `'none'`-like behavior) rather than raising at configuration time.
