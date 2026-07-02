from django.utils.encoding import force_str


def get_exception_error_msg(e):
    """
    Extract a human-readable string from any Django or Python exception.

    Handles ValidationError (with message_dict or message list), plain exceptions,
    and lists of errors — flattening them into a single space-joined string.
    """
    try:
        d = e.message_dict
        return " ".join([f'{field}: {get_exception_error_msg(err)}' for field, err in d.items()])
    except AttributeError:
        try:
            l = e.message
            l = l if isinstance(l, list) else [l]
            if len(l) == 1:
                return force_str(l[0])
            else:
                return " ".join([get_exception_error_msg(s) for s in l])
        except AttributeError:
            l = getattr(e, 'messages', getattr(e, 'error_list', e if isinstance(e, list) else [e]))
            if len(l) == 1:
                return force_str(l[0])
            else:
                return " ".join([get_exception_error_msg(s) for s in l])


class ConfigurationException(Exception):
    """Raised when the workflow configuration is invalid or incomplete."""


class BusinessException(Exception):
    """Raised when a workflow operation violates a business rule at runtime."""


# Configuration exceptions — raised during configure_workflow() or first access
# of a misconfigured model.

class InvalidWorkflowConfiguration(ConfigurationException):
    """The configure_workflow() call received an invalid config structure."""


class WorkflowModelNotConfigured(ConfigurationException):
    """A workflow operation was attempted on a model that has not been configured."""


class InvalidState(ConfigurationException):
    """A state name referenced in config or a transition does not exist."""


# Business-logic exceptions — raised during transition() or permission checks.

class TransitionNotAllowed(BusinessException):
    """The requested transition is not permitted for the current user or state."""


class WorkflowValidationError(BusinessException):
    """A consumer-defined validate_*() hook rejected the transition."""


class UnmanagedObject(BusinessException):
    """A workflow operation was attempted on an object not yet in the workflow."""


class StaleObject(BusinessException):
    """The object was modified by another transition since it was loaded."""


# Non-blocking transition feedback — raised from validate_* methods.

class TransitionWarning(Exception):
    """Non-blocking warning collected during transition validation; rendered as a yellow alert."""


class TransitionInfo(Exception):
    """Non-blocking informational message collected during validation; rendered as a blue alert."""
