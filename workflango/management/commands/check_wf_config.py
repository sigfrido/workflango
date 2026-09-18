from __future__ import print_function
from django.core.management.base import BaseCommand, CommandError

from workflango.management.utils import get_model_list

class Command(BaseCommand):

    help = 'Checks the workflow configuration for the specified models'

    def add_arguments(self, parser):
        parser.add_argument('models', nargs='*', metavar='appname.model',
            help='Models to check (default: every WorkflowModel subclass).')

    def handle(self, *args, **options):
        for model in get_model_list(*options['models']):
            try:
                model.wfm_config.check()
                print(f"OK: {model.__name__}")
            except Exception as e:
                raise CommandError(str(e))