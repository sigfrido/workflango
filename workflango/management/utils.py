# -*- coding: utf-8 -*-

from django.apps import apps as django_apps
from django.conf import settings
from django.core.mail import mail_admins
from django.core.management.base import CommandError

from workflango.models import WorkflowModel


def send_email_to_admins(subject, message):
    """
    Send an email to Django ADMINS.
    Override by setting WORKFLANGO_NOTIFY_FUNC in settings to a callable(subject, message).
    """
    notify_func = getattr(settings, 'WORKFLANGO_NOTIFY_FUNC', None)
    if notify_func:
        notify_func(subject, message)
    else:
        mail_admins(subject, message, fail_silently=True)

def get_model_list(*args):
    if not len(args):
        return [model
            for model in django_apps.get_models(include_auto_created=False)
            if issubclass(model, WorkflowModel)
        ]
    try:
        models = []
        for label in args:
            (app_name, model_name) = label.split('.')
            model = django_apps.get_model(app_name, model_name)
            if not model:
                raise ValueError(f"Unable to load model {label}")
            models.append(model)
        return models
    except Exception as e:
        raise CommandError(str(e)) from e
            
