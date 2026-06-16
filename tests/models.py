# -*- coding: utf-8 -*-

from workflango.models import WorkflowModel
from django.core.exceptions import ValidationError
from django.db.models import AutoField


class WorkflowModelValid(WorkflowModel):

    id = AutoField(primary_key=True)
    
    class Meta:
        app_label = 'tests'


    def __str__(self):
        return 'WorkflowModelValid %s' % (self.pk)


    def after_state_transition(self, previous_state):
        """
        This method is called anytime a transition has been completed
        """
        if not hasattr(self, 'transition_committed'):
            self.transition_committed = 0
        self.transition_committed += 1


    def validate_state_transition(self, user, current_state, new_state, new_owner, suspended):
        if hasattr(self, 'invalid_transition'):
            raise ValidationError('Invalidated generic transition: %s to %s' % (current_state, new_state))


    def validate_1_to_2(self, user):
        if hasattr(self, 'invalid_1_to_2'):
            raise ValidationError('Invalidated transition: 1 to 2')


    def validate_any_to_2(self, user):
        if hasattr(self, 'invalid_any_to_2'):
            raise ValidationError('Invalidated transition: any to 2')


    def validate_2_to_3(self, user):
        if hasattr(self, 'invalid_2_to_3'):
            raise ValidationError('Invalidated transition: 2 to 3')


    def get_candidate_users(self, for_state=None, privileges='ea', active=None):
        """
        Custom candidate users filter
        """
        user_queryset = super(WorkflowModelValid, self).get_candidate_users(for_state, privileges, active)
        if for_state == '1' and hasattr(self, 'exclude_group4'):
            return user_queryset.exclude(username='user4')
        return user_queryset



    workflow_defaults = {
        'properties' : {
            'edit_button_label' : 'Edit'
        },
        'admin' : [],
        'edit' : ['group1'],
        'read' : [],
    }

    workflow_phases = (

        (None, {
            'reachable_states' : {
                1 : {}
            },

            'admin' : ['group1', 'group4'],
            #edit is not set, should get it from defaults
            'read' : [],
        }),

        (1, {
            'reachable_states' : {
                2 : { 'caption' : 'exec 12' },
                3 : {},
            },

            'admin' : ['group1', 'group4'],
            'edit' : ['group2'],
            'read' : ['group3'],
        }),

        (2, {

            'reachable_states' : {
                3 : {},
                4 : { 'allow-reject' : False },
            },
            'admin' : ['group4'],
            'edit' : ['group3'],
            'read' : [],
            'allow_release' : 'no',
            'properties' : {
                'edit_button_label' : 'Change'
            }
        }),

        (3, {
            'reachable_states' : {},
            'admin' : [],
            'edit' : [],
            'read' : [],
            'is_closed' : True,
        }),

        (4, {
            'reachable_states' : {
                1 : {}, # required for testing reject_to_state
                0 : {
                    'allowed_groups': ['group4']
                }, # required for validating '0' config
            },
            'admin' : ['group4'],
            'edit' : ['group3'],
            'read' : [],
            'is_closed' : True,
        }),

        (0, { # put here to test that state keys are not being sorted
            'reachable_states' : {},
            'edit' : [],
        }),

    )

    
class WorkflowModelInvalid(WorkflowModel):
    id = AutoField(primary_key=True)

    class Meta:
        app_label = 'tests'
    
    def __str__(self):
        return 'TestModel %s' % (self.pk)
            
    
