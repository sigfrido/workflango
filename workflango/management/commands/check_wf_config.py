from __future__ import print_function
from django.core.management.base import BaseCommand, CommandError

from workflango.management.utils import get_model_list

class Command(BaseCommand):
    

    args = '[<appname.model>, <appname.model>...]'
    help = 'Verifica configurazione WFM per i model specificati'

    def handle(self, *args, **options):
        for model in get_model_list(*args):
            try:
                model.wfm_config.check()
                print(f"OK: {model.__name__}")
            except Exception as e:
                raise CommandError(str(e))