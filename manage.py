#!/usr/bin/env python
import os
import sys

if __name__ == '__main__':
    from tests.settings import SETTINGS
    from django.conf import settings
    if not settings.configured:
        SETTINGS['DATABASES'] = {
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': ':memory:',
            }
        }
        settings.configure(**SETTINGS)
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)
