from __future__ import print_function
from django.core.management.base import BaseCommand, CommandError

from workflango.user_groups import init_all_groups

class Command(BaseCommand):
    

    help = 'Crea i nuovi gruppi utenti'

    def handle(self, *args, **options):
        init_all_groups(True)
