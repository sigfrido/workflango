# Handle user / group relationship
from django.conf import settings
from django.contrib.auth.models import User, Group
from django.core.exceptions import ObjectDoesNotExist, ImproperlyConfigured
from django.utils.encoding import force_str



def group_is_valid(group_name):
    configured_groups = getattr(settings, 'WORKFLOW_USERS_GROUPS', None)
    if not configured_groups:
        return True

    valid_groups = [grp for (grp, descr) in configured_groups]
    if group_name not in valid_groups:
        return False
    return True


def group_is_valid_or_error(group_name):
    if not group_is_valid(group_name):
        raise ValueError(f'Undefined group: {group_name}')
    return True


def users_for_group(group_name, active=None):
    return users_for_groups([group_name], active)


def users_for_groups(groups_list, active=None):
    groups = Group.objects.filter(name__in=groups_list).distinct()
    if not groups.exists():
        return User.objects.none()
    qs = User.objects.filter(groups__in=groups)
    if active in (True, False):
        qs = qs.filter(is_active=active)
    return qs.order_by('username').distinct()



def user_group_add(user, group_name):
    """
    Adds a user to a group; will create the group if non-existent
    """
    return _user_group_add_remove(user, group_name, True)


def user_group_remove(user, group_name):
    """
    Remove user from group; will create the group if non-existent
    """
    return _user_group_add_remove(user, group_name, False)


def user_in_groups(user, groups):
    """
    Tests if the given user belongs to any of the given groups
    list or string with comma separated group names)
    If user is None or not authenticated, the result is None
    """
    if user and user.is_authenticated:
        if isinstance(groups, str):
            groups = [grp.strip() for grp in force_str(groups).split(',')]
        return user.in_groups(groups)
    else:
        return None    # False won't be correct


def _user_group_add_remove(user, group_name, do_add):
    group, created = get_or_create_group(group_name)
    if (group is not None):
        if (do_add):
            group.user_set.add(user)
        else:
            group.user_set.remove(user)
        return True
    return False


def get_or_create_group(group_name):
    """
    Return a group, will create it if needed
    Will raise excepion if group is not defined in settings.WORKFLOW_USERS_GROUPS (if any)
    """
    # Test if group has been defined in settings.
    # This is mainly for documentation purposes: we don't want users to create groups on the fly
    if not group_is_valid(group_name):
        raise ImproperlyConfigured(f'Group {group_name} does not exist in settings.WORKFLOW_USERS_GROUPS.')
    try:
        group = Group.objects.get(name = group_name)
        created = False
    except ObjectDoesNotExist:
        group = Group(name = group_name)
        group.save()
        created = True
    return (group, created)



def init_all_groups(verbose=False):
    """
    Initializes all configured groups
    """
    try:
        for (grp, descr) in settings.WORKFLOW_USERS_GROUPS:
            group, created = get_or_create_group(grp)
            if verbose:
                action = 'CREATED' if created else 'EXISTING'
                print(f'[{action}] {grp}: {descr}')
    except:
        raise ImproperlyConfigured('settings.WORKFLOW_USERS_GROUPS not found')



def get_groups_dict():
    groups_dict = {}
    for (name, descr) in settings.WORKFLOW_USERS_GROUPS:
        groups_dict[name] = descr
    return groups_dict
