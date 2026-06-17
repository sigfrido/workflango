# -*- coding: utf-8 -*-

SETTINGS = dict(

    INSTALLED_APPS = (
        'django.contrib.auth',
        'django.contrib.contenttypes',
        'workflango',
        'tests',
    ),

    # DATABASES = {
    #     "default": {
    #         'ENGINE' : 'django.db.backends.postgresql_psycopg2',
    #         'NAME' : 'gpvwf',
    #         'USER' : 'postgres',
    #         'PASSWORD' : 'pg5432',
    #         'HOST' : 'localhost',
    #         'PORT' : '5432',
    #     },
    # },

    WORKFLOW_USERS_GROUPS = (
        ('group1', 'test group 1'),
        ('group2', 'test group 2'),
        ('group3', 'test group 2'),
        ('group4', 'test group 2'),
        ('group_extra', 'test group extra'),
        ('GPV_APP_ADMIN', 'Application admin'),
    ),

    WORKFLOW_ADMIN = 'admin',

    WORKFLOW_ADMIN_GROUP = 'GPV_APP_ADMIN',

    # Limit transition message length
    WORKFLOW_TRANS_MSG_MAX_LEN = 4096,
    
    DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'


)

