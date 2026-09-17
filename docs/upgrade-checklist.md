# Upgrade checklist: pre-1.0 breaking renames

Actionable reference for migrating a consumer project (e.g. opus) to the current
`workflango` `[Unreleased]` state. Covers every breaking rename from this development
cycle, in the order they should be applied. Each item gives the exact old→new mapping,
a `grep` to find every call site in the consumer project, and what to actually change
(a plain rename vs. a value/config change). Run the greps from the consumer project's
root; none of them touch workflango itself, only how the consumer *calls* it.

Apply and test each section independently — they're unrelated to each other except
where noted, so you can land this over several small commits rather than one giant one.

---

## 1. Settings: unified `WF_` prefix

```
grep -rn "WORKFLOW_USERS_GROUPS\|WORKFLOW_ADMIN\b\|WORKFLOW_ADMIN_GROUP\|WORKFLOW_TRANS_MSG_MAX_LEN\|WORKFLANGO_ALLOW_IMPERSONATE\|WORKFLANGO_SNAPSHOT_ENABLED\|WORKFLANGO_ACCESS_DENIED_URL\|WORKFLANGO_NOTIFY_FUNC" --include=*.py .
```

| Old | New |
|---|---|
| `WORKFLOW_USERS_GROUPS` | `WF_USERS_GROUPS` |
| `WORKFLOW_ADMIN` | `WF_ADMIN` |
| `WORKFLOW_ADMIN_GROUP` | `WF_ADMIN_GROUP` |
| `WORKFLOW_TRANS_MSG_MAX_LEN` | `WF_TRANS_MSG_MAX_LEN` |
| `WORKFLANGO_ALLOW_IMPERSONATE` | `WF_ALLOW_IMPERSONATE` |
| `WORKFLANGO_SNAPSHOT_ENABLED` | `WF_SNAPSHOT_ENABLED` |
| `WORKFLANGO_ACCESS_DENIED_URL` | `WF_ACCESS_DENIED_URL` |
| `WORKFLANGO_NOTIFY_FUNC` | `WF_NOTIFY_FUNC` |

Plain rename, `settings.py` only. Nothing else reads these names.

---

## 2. `SebastianWorkflowSerializerMixin.datetime_format` → `wf_datetime_format`

Only relevant if you use `workflango.contrib.sebastian` **and** override this attribute
on a subclass (e.g. to change the state-badge date format).

```
grep -rn "datetime_format" --include=*.py .
```

Rename any subclass's `datetime_format = ...` override to `wf_datetime_format = ...`.
Only touch it if the class also extends `SebastianWorkflowSerializerMixin` — a bare
`datetime_format` on an unrelated class is not this.

---

## 3. Owner filter shortcuts: `-1`…`-6` → descriptive strings

```
grep -rn "search_wf_proprietario\|search_proprietario\|search_wf_owner" --include=*.py --include=*.html .
```

Query-param **values** for the Owner filter, not the field name (see §4 for that):

| Old | New |
|---|---|
| `-1` (Me) | `me` |
| `-2` (Me or none) | `me_or_none` |
| `-3` (None) | `none` |
| `-4` (Someone) | `someone` |
| `-5` (Not me) | `not_me` |
| `-6` (Not active) | `not_active` |

Check any hardcoded URL/link/test that passes one of these as a literal query-string
value (e.g. `?search_wf_owner=-1` or `kwargs={'search_wf_proprietario': '-3'}` in a
test). If you had a custom `-7`/"Away"-style extension, see the new
`WF_CUSTOM_OWNER_FILTERS` setting (README.md "Owner filter shortcuts") — it replaces
patching workflango directly.

---

## 4. `search_wf_*` field/query-param names: Italian → English

```
grep -rn "search_wf_fase\|search_wf_messaggio\|search_wf_sospeso\|search_wf_da_leggere\|search_wf_proprietario\|search_wf_data_min\|search_wf_data_max\|search_wf_stato_old" --include=*.py --include=*.html --include=*.js .
```

| Old | New |
|---|---|
| `search_wf_fase` | `search_wf_phase` |
| `search_wf_messaggio` | `search_wf_message` |
| `search_wf_sospeso` | `search_wf_suspended` |
| `search_wf_da_leggere` | `search_wf_unread` |
| `search_wf_proprietario` | `search_wf_owner` |
| `search_wf_data_min` | `search_wf_date_min` |
| `search_wf_data_max` | `search_wf_date_max` |
| `search_wf_stato_old` | `search_wf_history` |

Check: any custom filter form subclassing `WorkflowFilterForm`, any hardcoded
querystring in JS/templates/tests, any `WorkflowFilter`/`WorkflowFilterSetMixin`
subclass declaring its own `search_fields`/`declared_filters` entries alongside these.

---

## 5. Full "Phase vs State" rename

Rule: **"Phase is the class, State is the instance."** A `Phase` is the category (a
static string name, defined in `WorkflowConfig`). A `State` is the Django model
instance recording one point in an object's transition history — an object **is in**
a `State`, which **belongs to** a `Phase`. Everything below follows from that.

### 5a. Breaking — URL kwarg `nuovo_stato` → `destination_phase`

```
grep -rn "nuovo_stato" --include=*.py .
```

Two things to change together:
1. Every `urls.py` path using `ChangeStateView` (or any view built on
   `_BaseWorkflowTransitionMixin`/`WorkflowModelChangeState`) with a
   `<str:nuovo_stato>` path converter → `<str:destination_phase>`.
2. Every `reverse(..., kwargs={'nuovo_stato': ...})` call (views, tests, anywhere else
   building this URL by hand instead of via `obj.get_change_state_url(destination)`,
   which already builds the new kwarg name for you — no change needed at call sites
   using that method).

`ChangeStateView`/`ChangeStateForm` class names, the `change_state`/`change_state_form`
action names (DRF / sebastian GUI), and the `*_change_state` URL *name* pattern (e.g.
`mydocument_change_state`) are **unchanged** — only the path *kwarg* renamed.

### 5b. Breaking — config schema key `'reachable_states'` → `'reachable_phases'`

```
grep -rn "'reachable_states'\|\"reachable_states\"" --include=*.py .
```

Every `workflow_phases`/`workflow_states` config tuple passed to
`configure_workflow()` (or set as a class attribute consumed by it) uses this as a
literal dict key inside each phase's config dict:

```python
# before
(None, {'reachable_states': {'draft': {}}}),
# after
(None, {'reachable_phases': {'draft': {}}}),
```

This is silent if missed — an old `'reachable_states'` key is just ignored (no
error), and the phase becomes unreachable from everywhere, which
`WorkflowConfig.check()` (called by `check_wf_config` management command) *should*
catch as `InvalidWorkflowConfiguration: Unreachable phase for ...` — **run
`manage.py check_wf_config` after this change** to confirm nothing was missed.

### 5c. Internal API renames — check for keyword-argument usage

These are safe if every call site uses positional arguments (the overwhelming common
case) — only **keyword** calls (`some_call(new_state=...)`) or **overrides** (a
subclass defining a method with the old signature) break. Grep each old name; for any
hit, check whether it's a positional call (no change needed) or a keyword
call/override/import (needs the rename).

**`WorkflowConfig`** (`<Model>.wfm_config.<method>()`):

```
grep -rn "\.get_state_config(\|\.get_states_list(\|\.get_state_order(\|\.editors_for_state(\|\.get_candidate_users_for_state(\|\.get_states_for_permissions(\|\.check_unreachable_states(\|\.reach_states_from(" --include=*.py .
```

| Old | New |
|---|---|
| `get_state_config` | `get_phase_config` |
| `get_states_list` | `get_phases_list` |
| `get_state_order` | `get_phase_order` |
| `editors_for_state` | `editors_for_phase` |
| `get_candidate_users_for_state` | `get_candidate_users_for_phase` |
| `get_states_for_permissions` | `get_phases_for_permissions` |
| `check_unreachable_states` | `check_unreachable_phases` |
| `reach_states_from` | `reach_phases_from` |

**`InstanceWorkflowManager`** (`instance.wfm.<method>()`):

```
grep -rn "\.wfm\.transition(.*new_state\s*=\|\.wfm\.transition_allowed(.*new_state\s*=\|\.reject_to_state(\|\.get_transition(.*dest_state\s*=" --include=*.py .
```

| Old | New |
|---|---|
| `.transition(user, new_state=..., ...)` (keyword only) | `new_phase=` |
| `.transition_allowed(user, new_state=..., ...)` (keyword only) | `new_phase=` |
| `.reject_to_state(user, phase, ...)` | `.reject_to_phase(user, phase, ...)` (method renamed — **always** update, not just keyword calls) |
| `.get_transition(dest_state=..., ...)` (keyword only) | `dest_phase=` |

**`State` model**:

```
grep -rn "\.get_previous_different_state(\|\.wfm_state_config(\|\.get_state_property(\|def get_previous_different_state\|def wfm_state_config\|def get_state_property\|def get_state_order" --include=*.py .
```

| Old | New |
|---|---|
| `.get_previous_different_state(state_str=None)` | `.get_previous_different_phase(phase=None)` (method renamed — always update) |
| `.wfm_state_config()` | `.wfm_phase_config()` (method renamed — always update) |
| `.get_state_property(name)` | `.get_phase_property(name)` (method renamed — always update) |
| `.get_state_order(relative_to=None)` | `.get_phase_order(relative_to=None)` (method renamed — always update; note this is a *different* method from `WorkflowConfig.get_phase_order`, same name, different receiver) |
| `.find_last_state(state)` | **unchanged name** — genuinely returns a `State` instance. Only its keyword param, if used (`state=...`), becomes `phase=...` |

**`WorkflowModel`**:

```
grep -rn "\.current_state_str(\|def current_state_str\|\.get_candidate_users(.*for_state\s*=\|def get_candidate_users" --include=*.py .
```

| Old | New |
|---|---|
| `.current_state_str(for_none='')` | `.current_phase_str(for_none='')` (method renamed — always update) |
| `.get_candidate_users(for_state=..., ...)` (keyword only) | `for_phase=` — **also check any override**: `def get_candidate_users(self, for_state=None, ...)` in a subclass must be renamed to `for_phase` to keep matching the base signature |

**`WFTransitionDescriptor`** (obtained via `instance.wfm.get_transition(...)`, or constructed directly):

```
grep -rn "\.state_property(\|\.state_help_topic\|\.state_description\|\.get_destination_state_property(\|WFTransitionDescriptor(.*dest_state\s*=" --include=*.py --include=*.html .
```

| Old | New |
|---|---|
| `.state_property(prop, defa=None)` | `.phase_property(...)` (method renamed — always update) |
| `.state_help_topic` | `.phase_help_topic` (property renamed — always update) |
| `.state_description` | `.phase_description` (property renamed — always update) |
| `.get_destination_state_property(prop, defa=None)` | `.get_destination_phase_property(...)` (method renamed — always update) |
| `WFTransitionDescriptor(obj, dest_state=..., ...)` (keyword only) | `dest_phase=` |

**Unchanged, confirmed still correct under the rule** — do *not* rename these even
though they mention "state": `WFTransitionDescriptor.state` (returns the real current
`State`), `.phase_str`, `.destination` (both already phase strings),
`State.phase_str()` (deliberately accepts either a `State` instance or a phase
string), `State.find_last_state()` (returns a real `State`),
`after_state_transition(self, previous_state, ...)` hook (its `previous_state` really
is a `State` instance).

**Exception class**:

```
grep -rn "InvalidState\b" --include=*.py .
```

`from workflango.exceptions import InvalidState` → `InvalidPhase`. Check any
`except InvalidState:` blocks too.

**Consumer-overridable validation hook** (undocumented but real — a plain method
matched by name on your `WorkflowModel` subclass):

```
grep -rn "def validate_state_transition" --include=*.py .
```

`def validate_state_transition(self, user, current_state, new_state, new_owner, suspended):`
→ `def validate_phase_transition(self, user, current_phase, new_phase, new_owner, suspended):`
(rename the method definition itself in any subclass that has one; the two positional
args it receives were always phase strings, only their names/the method name changed).
The per-phase dynamic hooks (`validate_<phase>_to_<phase>`, `validate_any_to_<phase>`,
`validate_<phase>_to_any`) are **unchanged** — they were already phase-value-based.

**Test helpers** (`workflango.mixins_tests.WorkflowTestMixin`/`GUITestMixin` — only
matters if you call these by keyword, e.g. in your own test suite):

```
grep -rn "\.transition(.*new_state\s*=\|\.transition_allowed(.*new_state\s*=\|\.ok_transition(.*new_state\s*=\|\.get_change_state_view(.*state\s*=\|\.post_change_state_view(.*state\s*=" --include=*.py .
```

`transition()`/`transition_allowed()`/`ok_transition()`'s `new_state` param → `new_phase`;
`get_change_state_view()`/`post_change_state_view()`'s `state` param → `phase`.

---

## After applying all sections

```
manage.py check_wf_config   # catches a missed 'reachable_states' -> 'reachable_phases' as InvalidWorkflowConfiguration
manage.py test              # your own suite — catches everything else (keyword-arg breaks, hook renames, URL kwarg)
```

Then a final sweep to confirm nothing was missed:

```
grep -rln "nuovo_stato\|InvalidState\b\|get_state_config\|get_states_list\|get_state_order\|editors_for_state\|get_candidate_users_for_state\|get_states_for_permissions\|check_unreachable_states\|reach_states_from\|wfm_state_config\|get_state_property\|get_previous_different_state\|current_state_str\|reject_to_state\|validate_state_transition\|'reachable_states'" --include=*.py --include=*.html .
```

Zero matches (outside your own historical changelog/commit messages, if any) means the
migration is complete.
