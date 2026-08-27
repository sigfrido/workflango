from django import template
from django.utils.html import format_html

from ..i18n import wgettext

register = template.Library()

@register.simple_tag
def wtrans(message):
    """
    Translates a library-owned string under the "workflango" msgctxt.
    Usage::
        {% wtrans "Cancel" %}
    See workflango/i18n.py for why this context wrapper exists.
    """
    return wgettext(message)


@register.filter
def in_groups(user, groups):
    """
    Returns a boolean if the user is in the given group/comma-separated list of groups
    Usage::
        {% if user|in_groups:"Friends" %}, {% if user|in_groups:"Friends,Foes" %}
    """
    return user.in_groups(groups)



@register.filter
def state_property(state_instance, property_name):  
    try:
        return state_instance.get_state_property(property_name)
    except:
        return None
        
        
        
@register.filter
def has_unread(user, obj):
    """
    {% if request.user|has_unread:object %}
    """
    return obj.current_state.unread and (obj.current_state.owner == user)


@register.filter
def change_state_url(obj, destination):
    """
    {{ object|change_state_url:"take-ownership" }}
    """
    return obj.get_change_state_url(destination)


@register.filter
def owned_by(state, request):
    """
    Impersonation-aware ownership check for templates: true only if request.user is the
    same actor that produced `state` -- correctly distinguishing an admin impersonating
    the owner (before an explicit take_ownership() reclaim) from the owner acting for
    themselves, unlike a raw `state.owner == request.user` comparison. See
    State.owned_by() and GitHub issue #1.
    Usage::
        {% if st|owned_by:request %}
    """
    if not state:
        return False
    return state.owned_by(request.user, getattr(request, 'impersonated_by', None))


@register.simple_tag
def state_operator(state):
    """
    Renders the user who performed a transition (State.user), annotated with the real
    actor when an admin performed it on the user's behalf via impersonation
    (State.impersonated_by). HTML output -- for a plain-text equivalent (e.g. inside an
    HTML attribute like title="...") use the `state_operator_text` filter instead.
    Usage::
        {% state_operator state %}
    """
    if not state or not state.user:
        return '-'
    if state.impersonated_by:
        return format_html(
            '{} <span class="text-muted">({})</span>',
            state.user,
            wgettext('impersonated by %(admin)s') % {'admin': state.impersonated_by},
        )
    return format_html('{}', state.user)


@register.filter
def state_operator_text(state):
    """
    Plain-text equivalent of `state_operator`, for use inside an HTML attribute.
    Usage::
        title="{{ state|state_operator_text }}"
    """
    if not state or not state.user:
        return '-'
    if state.impersonated_by:
        return wgettext('%(user)s (impersonated by %(admin)s)') % {
            'user': state.user, 'admin': state.impersonated_by,
        }
    return str(state.user)
    
