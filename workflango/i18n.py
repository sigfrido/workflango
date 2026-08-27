"""
Shared i18n helper for workflango's own GUI chrome.

Every translatable string owned by the library (not the consumer's domain
content) uses the translation context ``"workflango"``, so it can never be
silently shadowed by another installed app's plain-context catalog defining
the same English word (``django.contrib.admin`` ships its own "Delete",
"Save", "History", ... translations, and if it happens to load after
workflango in ``INSTALLED_APPS``, a plain-context ``gettext()`` call here
would pick up admin's translation instead of workflango's).

Use `wgettext()` from Python and the `{% wtrans %}` template tag
(`templatetags/workflow_tags.py`) instead of calling `pgettext()` /
`{% trans ... context "workflango" %}` directly — both are thin wrappers
around this same context, so the literal string "workflango" only needs to
be typed once, here.
"""
from django.utils.translation import pgettext, pgettext_lazy

CONTEXT = 'workflango'


def wgettext(message: str) -> str:
    """`pgettext(CONTEXT, message)` — Python-side shorthand; mirrors the
    `{% wtrans %}` template tag."""
    return pgettext(CONTEXT, message)


def wgettext_lazy(message: str):
    """
    `pgettext_lazy(CONTEXT, message)` — for strings evaluated once at import
    time (module-level dicts/tuples, e.g. form field `choices`), where eager
    `wgettext()` would bake in whichever language was active at process
    startup instead of the requesting user's language.
    """
    return pgettext_lazy(CONTEXT, message)
