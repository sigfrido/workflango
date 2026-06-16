from django import template

register = template.Library()

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
    
