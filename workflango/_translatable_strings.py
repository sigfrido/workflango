"""
Extraction-only registry for strings used via `{% wtrans %}` or `wgettext()`/
`wgettext_lazy()`.

`django-admin makemessages` recognizes a fixed set of literal function/tag
names when scanning source: the built-in `{% trans %}`/`{% blocktrans %}`
template tags, and `gettext`/`pgettext`/`pgettext_lazy`/... calls in Python
files. It has no idea `{% wtrans %}` (templatetags/workflow_tags.py) or
`wgettext()`/`wgettext_lazy()` (i18n.py) exist -- all are thin wrappers,
invisible to extraction -- so a template using only `{% wtrans "X" %}`, or
Python code calling only `wgettext("X")`, would silently vanish from the .po
file with no warning. This module exists purely so makemessages' ordinary
Python-file extraction (which *does* understand real `pgettext()` calls)
picks these strings up. `_strings()` below is never called anywhere --
makemessages only scans the source text, it doesn't execute this module --
so the calls are wrapped in a function specifically to keep `pgettext()`
from ever running at import time (pdoc and any other bare `import
workflango...` would otherwise crash with `AppRegistryNotReady`, since
translation needs `django.setup()` to have run first).

`models.TRANS_TYPE_MAP` deserves a special mention: its values are plain
(untranslated) msgids looked up and translated lazily by
`State.transition_type_display()` -- makemessages cannot see through that
dict indirection at all, so every value needs a literal entry here too.

Whenever you add or change a `{% wtrans "..." %}` or `wgettext("...")` /
`wgettext_lazy("...")` call anywhere in the library, add or update the
matching line here, then re-run (from `workflango/`):

    django-admin makemessages -l it --no-location
    django-admin compilemessages

Any `# Translators:` comment explaining a placeholder (e.g. `%(phase)s`)
must live on the line directly above the `pgettext()` call *here*, not at
the `wgettext()` call site -- makemessages only reads comments adjacent to
the literal extraction point it recognizes, which is always this file.
"""
# NOTE: this must call the real `pgettext` directly, NOT the `wgettext()` /
# `wgettext_lazy()` wrappers from .i18n -- xgettext's Python extraction only
# recognizes a fixed set of literal function names (gettext, pgettext,
# pgettext_lazy, ngettext, ...); a custom wrapper name is just as invisible
# to it as the {% wtrans %} tag is.
from django.utils.translation import pgettext


def _strings():  # pragma: no cover - never called, see module docstring
    return (
        # models.TRANS_TYPE_MAP values (see docstring above)
        pgettext('workflango', 'Undefined'),
        pgettext('workflango', 'Created'),
        pgettext('workflango', 'Delegated'),
        pgettext('workflango', 'Transition and assignment'),
        pgettext('workflango', 'Rejected'),
        pgettext('workflango', 'Resubmitted'),
        pgettext('workflango', 'Assigned'),
        pgettext('workflango', 'Reassigned'),
        pgettext('workflango', 'Transition'),
        pgettext('workflango', 'Released'),
        pgettext('workflango', 'Snatched'),
        pgettext('workflango', 'Taken in charge'),
        pgettext('workflango', 'Suspension'),
        pgettext('workflango', 'Resumed'),
        pgettext('workflango', 'Claimed via impersonation'),
        pgettext('workflango', 'Reclaimed'),

        # templatetags/workflow_tags.py -- state_operator / state_operator_text
        # Translators: %(admin)s/%(user)s are usernames, substituted after translation --
        # keep them verbatim.
        pgettext('workflango', 'impersonated by %(admin)s'),
        pgettext('workflango', '%(user)s (impersonated by %(admin)s)'),

        # drf.py -- API-level PermissionDenied/ValidationError messages
        pgettext('workflango', 'Access denied: user is neither the owner nor an administrator.'),
        pgettext('workflango', 'The object does not have an active state yet.'),
        pgettext('workflango', 'Only the current owner can change the read state.'),
        pgettext('workflango', 'Impersonation is not enabled (WORKFLANGO_ALLOW_IMPERSONATE).'),
        # Translators: %(user_id)s is a numeric id, substituted after translation.
        pgettext('workflango', 'User %(user_id)s not found or not active.'),
        pgettext('workflango', 'User %(user_id)s not found.'),
        # Translators: %(user)s is a username, substituted after translation.
        pgettext('workflango', 'Not authorized to act as %(user)s.'),
        pgettext('workflango', 'Invalid value: expected an integer.'),

        # contrib/sebastian.py -- optional drf-sebastian integration, GUI field/action labels
        pgettext('workflango', 'State'),

        # wf_transition.py -- WFTransitionDescriptor.caption fallback (no explicit
        # 'caption' configured on the transition)
        # Translators: %(destination)s is the target phase name, substituted after
        # translation -- keep it verbatim.
        pgettext('workflango', 'Send back to %(destination)s'),
        pgettext('workflango', 'Go to: %(destination)s'),

        # views_mixins.py / views.py -- runtime messages and access-denied text
        # Translators: %(destination)s/%(phase)s/%(error)s tokens are placeholders
        # substituted after translation -- keep them verbatim.
        pgettext('workflango', 'The transition to %(destination)s failed: %(error)s.'),
        pgettext('workflango', 'Transition to state completed: %(phase)s'),
        pgettext('workflango', 'The transition will be performed as ADMIN; the following errors were detected: %(error)s.'),
        pgettext('workflango', 'Cannot perform the transition: %(error)s.'),
        pgettext('workflango', 'Unexpected error: %(error)s.'),
        pgettext('workflango', 'You do not have access to this resource.'),
        pgettext('workflango', 'Access error: you do not have creation privileges.'),
        pgettext('workflango', 'The record is suspended. Cannot proceed.'),
        pgettext('workflango', 'You cannot view this resource.'),
        pgettext('workflango', 'The object was marked as unread.'),
        pgettext('workflango', 'The object was marked as read.'),

        # views.py -- ChangeStateView.command_captions and transition titles
        pgettext('workflango', 'Take ownership'),
        pgettext('workflango', 'The object will be taken in charge.'),
        pgettext('workflango', 'Release'),
        pgettext('workflango', 'The object will be released and become available again for take ownership.'),
        pgettext('workflango', 'Reject to previous state'),
        pgettext('workflango', 'The object will be rejected to the phase and user that previously assigned it to you.'),
        pgettext('workflango', 'Reject'),
        pgettext('workflango', 'Delegate'),
        pgettext('workflango', 'The object will be delegated to the selected user.'),
        pgettext('workflango', 'Assign'),
        pgettext('workflango', 'The object will be assigned to the selected user.'),
        pgettext('workflango', 'Suspend'),
        pgettext('workflango', 'The object will be suspended.'),
        pgettext('workflango', 'Resume'),
        pgettext('workflango', 'The object will be resumed.'),
        pgettext('workflango', 'Confirm the transition to phase: %(phase)s'),
        pgettext('workflango', 'Transition to phase: %(phase)s'),
        pgettext('workflango', 'None'),

        # forms.py -- ChangeStateForm / WorkflowFilterForm labels, placeholders, errors
        pgettext('workflango', 'New owner'),
        pgettext('workflango', 'Message'),
        pgettext('workflango', 'Required'),
        pgettext('workflango', 'Optional'),
        pgettext('workflango', 'Message for the recipient (%(opt)s)'),
        pgettext('workflango', 'The message is %(len)s characters long, the maximum allowed is %(max)s.'),
        pgettext('workflango', 'Enter at least one non-space character'),
        pgettext('workflango', 'Owner'),
        pgettext('workflango', 'Type a name'),
        pgettext('workflango', 'Phase'),
        pgettext('workflango', 'Type a phase'),
        pgettext('workflango', 'Text contained in the message'),
        pgettext('workflango', 'Advanced text search: adoption or signature'),
        pgettext('workflango', 'Unread'),
        pgettext('workflango', 'History'),
        pgettext('workflango', 'Following'),
        pgettext('workflango', 'Min date'),
        pgettext('workflango', 'Minimum entry date into the current phase or the selected phases'),
        pgettext('workflango', 'Max date'),
        pgettext('workflango', 'Maximum entry date into the current phase or the selected phases'),

        # filters.py / filtersets.py -- search widget choices and descriptions
        pgettext('workflango', 'Yes'),
        pgettext('workflango', 'No'),
        pgettext('workflango', 'Also past'),
        pgettext('workflango', 'Only past'),
        pgettext('workflango', 'Me'),
        pgettext('workflango', 'Me or none'),
        pgettext('workflango', 'Not me'),
        pgettext('workflango', 'Someone'),
        pgettext('workflango', 'Not active'),
        pgettext('workflango', 'Away'),
        pgettext('workflango', 'Current'),
        pgettext('workflango', 'Invalid boolean value (%(value)s): allowed 1/0, t(rue)/f(alse), y(es)/n(o)'),
        pgettext('workflango', 'Error in the filter for field %(field)s: %(error)s'),
        pgettext('workflango', 'Workflow phase'),
        pgettext('workflango', 'Workflow transition message'),
        pgettext('workflango', 'The workflow is in a suspended state'),
        pgettext('workflango', 'The record has not yet been read by the assignee'),
        pgettext('workflango', 'Record owner'),
        pgettext('workflango', 'User id'),
        pgettext('workflango', 'Minimum entry date into the phase'),
        pgettext('workflango', 'Maximum entry date into the phase'),
        pgettext('workflango', 'Search past states'),

        # Used via {% wtrans %} in templates (some also listed above from Python):
        pgettext('workflango', 'unassigned'),
        pgettext('workflango', 'Current state'),
        pgettext('workflango', 'View state history'),
        pgettext('workflango', 'State history'),
        pgettext('workflango', 'suspended'),
        pgettext('workflango', 'from'),
        pgettext('workflango', 'Object'),
        pgettext('workflango', 'Current phase'),
        pgettext('workflango', 'Previous owner in phase'),
        pgettext('workflango', 'Recipient'),
        pgettext('workflango', 'Reject to phase'),
        pgettext('workflango', 'Cancel'),
        pgettext('workflango', 'Take ownership (ADMIN)'),
        pgettext('workflango', 'Reassign (ADMIN)'),
        pgettext('workflango', 'user'),
        pgettext('workflango', 'REJECTED'),
        pgettext('workflango', 'RESUBMITTED'),
        pgettext('workflango', 'Mark as read'),
        pgettext('workflango', 'Mark as unread'),
        pgettext('workflango', 'Back to detail'),
        pgettext('workflango', 'Transition'),
        pgettext('workflango', 'Date'),
        pgettext('workflango', 'Operator'),
    )
