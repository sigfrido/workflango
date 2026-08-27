from django.contrib.auth import get_user_model

IMPERSONATE_SESSION_KEY = '_workflow_impersonate_user_id'


class ImpersonateMiddleware:
    """
    If the logged-in user is a superuser and has an active impersonation session,
    swaps request.user for the impersonated target for the rest of the request and
    stashes the real admin on request.impersonated_by.

    Everything downstream -- views, permission checks, workflow transitions via
    workflango's _BaseWorkflowTransitionMixin.check_and_transition(), templates --
    reads request.user as the impersonated identity; request.impersonated_by is the
    only way back to who is really logged in. This is exactly the contract
    workflango's own transition-performing view mixins already expect
    (see workflango/views_mixins.py: `getattr(self.request, 'impersonated_by', None)`).

    Must run immediately after AuthenticationMiddleware (which sets the real
    request.user from the session) and before anything else reads request.user.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user_id = (
            request.session.get(IMPERSONATE_SESSION_KEY)
            if request.user.is_authenticated and request.user.is_superuser
            else None
        )
        if user_id:
            try:
                impersonated = get_user_model().objects.get(pk=user_id, is_active=True)
            except get_user_model().DoesNotExist:
                impersonated = None
            if impersonated:
                request.impersonated_by = request.user
                request.user = impersonated
            else:
                request.session.pop(IMPERSONATE_SESSION_KEY, None)
        return self.get_response(request)
