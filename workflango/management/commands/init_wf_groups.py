from __future__ import print_function
from django.core.management.base import BaseCommand, CommandError

from workflango.user_groups import init_all_groups

class Command(BaseCommand):
    

    help = 'Creates the configured user groups (settings.WF_USERS_GROUPS)'

    def handle(self, *args, **options):
        init_all_groups(True)
