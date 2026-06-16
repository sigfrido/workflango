# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.test import TransactionTestCase, TestCase
from django.core.exceptions import  ImproperlyConfigured, ValidationError
from django.contrib.auth.models import User
from django.conf import settings
from workflango.exceptions import (InvalidWorkflowConfiguration, InvalidState,
    TransitionNotAllowed, UnmanagedObject, StaleObject)
from workflango.models import State, transition_done, WorkflowModel
from workflango.wf_config import WorkflowConfig
from workflango.wf_transition import WFTransitionDescriptor
from tests.models import WorkflowModelValid, WorkflowModelInvalid

from django.db import IntegrityError, transaction


import unittest
import warnings

from workflango.user_groups import (user_group_add, user_group_remove,
    user_in_groups,
    users_for_group, users_for_groups,
    group_is_valid, group_is_valid_or_error)


SKIP_TESTS = not getattr(settings, 'STANDALONE_TESTS', False)

_tdd = {}
def _transition_done_handler(sender, **kwargs):
    global _tdd
    _tdd = {}
    _tdd.update(kwargs)
    #~ _transition_done_data.update(kwargs)


@unittest.skipIf(SKIP_TESTS, "Please run workflow tests with run_standalone_tests.py")
class WorkflowConfigTest(TestCase):

    def setUp(self):
        self.wc = WorkflowConfig(None,
            WorkflowModelValid.workflow_phases,
            WorkflowModelValid.workflow_defaults
        )

    def test_config(self):
        states_list = self.wc.get_states_list()
        self.assertEqual(states_list, ('1', '2', '3', '4', '0'))
        self.assertEqual(self.wc.get_state_order(None), 0)
        self.assertEqual(self.wc.get_state_order('1'), 1)
        self.assertEqual(self.wc.get_state_order('0'), 5)
        with self.assertRaises(InvalidState):
            self.assertEqual(self.wc.get_state_order('babic'), -1)


    def test_editors_for_state(self):
        # 'admin' : ['group1', 'group4'],  'edit' : ['group2'],
        groups = self.wc.editors_for_state('1', False)
        self.assertEqual(['group2'], groups)

        groups = self.wc.editors_for_state('1', True)
        self.assertIn('group1', groups)
        self.assertIn('group4', groups)
        self.assertIn('group2', groups)



@unittest.skipIf(SKIP_TESTS, "Please run workflow tests with run_standalone_tests.py")
class WorkflowTest(TransactionTestCase):

    @classmethod
    def setUpClass(cls):
        super(WorkflowTest, cls).setUpClass()
        if SKIP_TESTS:
            return
        cls.OkModel = WorkflowModelValid
        cls.OkModel.configure_workflow()


    def setUp(self):
        State.objects.all().delete()
        self.OkModel.objects.all().delete()
        User.objects.all().delete()

        self.admin = User.objects.create(username="admin", password="pol")
        self.user_1 = User.objects.create(username="user1", password="pol")
        self.user_1_b = User.objects.create(username="user1_b", password="pol")
        self.user_2 = User.objects.create(username="user2", password="pol")
        self.user_3 = User.objects.create(username="user3", password="pol")
        self.user_4 = User.objects.create(username="user4", password="pol")
        self.user_3_b = User.objects.create(username="user3_b", password="pol")
        self.user_3_c = User.objects.create(username="user3_c", password="pol")

        user_group_add(self.user_1, 'group1')
        user_group_add(self.user_1_b, 'group1')
        user_group_add(self.user_1, 'group_extra')
        user_group_add(self.user_2, 'group2')
        user_group_add(self.user_3, 'group3')
        user_group_add(self.user_3_b, 'group3')
        user_group_add(self.user_3_c, 'group3')
        user_group_add(self.user_4, 'group4')

        user_group_add(self.user_1, 'GPV_APP_ADMIN')
        user_group_add(self.admin, 'GPV_APP_ADMIN')

        self.OkModel.wfm_config.clear_cached_admins()


    def tearDown(self):
        super(WorkflowTest, self).tearDown()


    def create(self, user=None):
        instance = self.OkModel.objects.create()
        if user:
            instance.wfm.transition(user, 1, user)
        return instance


    # test user_groups
    def test_user_group_add_remove(self):
        user = User.objects.create(username="test_grp", password="pol")
        self.assertEqual(user.groups.count(), 0)
        with self.assertRaises(ImproperlyConfigured):
            # Try to create group on the fly, and fail
            user_group_add(user, 'unconfigured_group')
        self.assertTrue(user_group_add(user, 'group1'))
        self.assertEqual(user.groups.count(), 1)
        self.assertTrue(user.groups.filter(name='group1').exists())
        # Test remove
        self.assertTrue(user_group_remove(user, 'group1'))
        self.assertFalse(user.groups.filter(name='group1').exists())
        self.assertEqual(user.groups.count(), 0)


    def test_user_in_groups(self):
        self.assertTrue(user_in_groups(self.user_1, 'group1, group2'))
        self.assertTrue(user_in_groups(self.user_1, 'group3, group_extra'))
        self.assertTrue(user_in_groups(self.user_1, 'group1, group_extra'))
        self.assertFalse(user_in_groups(self.user_1, 'group3'))

        self.assertTrue(self.user_1.in_groups('group1, group2'))
        self.assertTrue(self.user_1.in_groups('group3, group_extra'))
        self.assertTrue(self.user_1.in_groups('group1, group_extra'))
        self.assertFalse(self.user_1.in_groups('group3'))


    def test_user_in_groups_list(self):
        self.assertTrue(user_in_groups(self.user_1, ['group1', 'group2']))
        self.assertTrue(user_in_groups(self.user_1, ['group3', 'group_extra']))
        self.assertTrue(user_in_groups(self.user_3, ['group3']))
        self.assertFalse(user_in_groups(self.user_3, ['little-frogs']))

        self.assertTrue(self.user_1.in_groups(['group1', 'group2']))
        self.assertTrue(self.user_1.in_groups('group3', 'group_extra'))
        self.assertTrue(self.user_3.in_groups(['group3']))
        self.assertFalse(self.user_3.in_groups(['little-frogs']))


    def test_users_for_group(self):
        # Tutti gli utenti
        users = users_for_group('group1')[:]
        self.assertTrue(self.user_1 in users)
        self.assertTrue(self.user_1_b in users)
        self.assertEqual(len(users), 2)

        self.user_1.is_active = False
        self.user_1.save()

        # True: solo utenti attivi
        users = users_for_group('group1', True)[:]
        self.assertCountEqual(users, [self.user_1_b])

        # False -> solo utenti non attivi
        users = users_for_group('group1', False)[:]
        self.assertCountEqual(users, [self.user_1])


    def test_users_for_groups(self):
        us = users_for_groups(['group1', 'group2'])
        users = us[:]
        self.assertTrue(self.user_1 in users and self.user_1_b in users and self.user_2 in users)
        self.assertEqual(len(users), 3)
        self.user_1.is_active = False
        self.user_1.save()
        us = users_for_groups(['group1', 'group2'], True)
        users = us[:]
        self.assertTrue(self.user_1_b in users and self.user_2 in users)
        self.assertEqual(len(users), 2)
        self.assertFalse(self.user_1 in users)


    def test_group_is_valid(self):
        self.assertTrue(group_is_valid('group1'))
        self.assertFalse(group_is_valid('non_existent_group'))


    def test_group_is_valid_or_error(self):
        self.assertTrue(group_is_valid_or_error('group1'))
        with self.assertRaises(ValueError):
            group_is_valid_or_error('non_existent_group')


    # Test WF Manager

    def test_invalid_workflow_config(self):

        with self.assertRaises(InvalidWorkflowConfiguration):
            WorkflowModelInvalid.configure_workflow(None)
    

    def test_valid_workflow_config(self):
        instance = self.OkModel()

        model_config = self.OkModel.wfm_config
        instance_config = instance.wfm_config

        self.assertEqual(model_config, instance_config)

        self.assertTrue(model_config[None]['properties']['edit_button_label'] == model_config['1']['properties']['edit_button_label'])
        self.assertTrue(model_config[None]['properties']['edit_button_label'] != model_config['2']['properties']['edit_button_label'])


    def test_wf_admin(self):
        cfg = self.OkModel.wfm_config
        self.assertEqual(cfg.admin(), self.admin)
        self.assertTrue(cfg.is_admin(self.admin))
        self.assertTrue(cfg.is_admin(self.user_1))
        self.assertFalse(cfg.is_admin(self.user_2))


    def test_get_states_list_all(self):
        states_list = self.OkModel.wfm_config.get_states_list()
        self.assertEqual(states_list, ('1', '2', '3', '4', '0'))


    def test_get_state_order(self):
        self.assertEqual(self.OkModel.wfm_config.get_state_order(None), 0)
        self.assertEqual(self.OkModel.wfm_config.get_state_order('1'), 1)
        self.assertEqual(self.OkModel.wfm_config.get_state_order('0'), 5)
        with self.assertRaises(InvalidState):
            self.assertEqual(self.OkModel.wfm_config.get_state_order('babic'), -1)


    def test_state_helpers(self):
        instance = self.create(self.user_1)
        state = instance.reload_current_state()

        conf = state.wfm_state_config()
        self.assertEqual(conf['edit'], ['group2'])

        #testing properties
        self.assertEqual(state.get_state_property('edit_button_label'), 'Edit')
        self.assertEqual(state.get_state_property('your_uncle_name'), None)

        self.assertEqual(state.get_state_order(), 1)
        self.assertEqual(state.get_state_order(3), -2)
        self.assertEqual(state.get_state_order('2'), -1)
        self.assertEqual(state.get_state_order(1), 0)


    def test_get_states_helper(self):
        instance_1 = self.create()

        # assign record, Admin only: from None to new user; reject -> back to user (Admin)
        with transaction.atomic():
            st1 = instance_1.wfm.transition(self.user_1, 1, self.user_1)
            st2 = instance_1.wfm.transition(self.user_1, 2, self.user_4)
            st3 = instance_1.wfm.transition(self.user_4, 2, self.user_3)
            st4 = instance_1.wfm.transition(self.user_3, 2, self.user_4)

        states = list(instance_1.wfm.get_states())
        self.assertEqual(st1.pk, states[0].pk)
        self.assertEqual(st2.pk, states[1].pk)
        self.assertEqual(st3.pk, states[2].pk)
        self.assertEqual(st4.pk, states[3].pk)




    def test_transition(self):
        instance = self.create(self.user_1)
        state = instance.reload_current_state()
        self.assertTrue(state.instance == instance)

        # , user_1 is no editor in state 2
        with self.assertRaises(TransitionNotAllowed):
            instance.wfm.transition(self.user_1, 2, self.user_1)

        with self.assertRaises(TransitionNotAllowed):
            instance.wfm.transition(self.user_1, 2, self.user_2)

        with self.assertRaises(TransitionNotAllowed):
            instance.wfm.transition(self.user_2, 3, self.user_2)


    def test_transition_owner_active(self):
        instance = self.OkModel.objects.create()
        instance.wfm.transition(self.user_1, 1, self.user_1)
        self.user_3.is_active = False
        self.user_3.save()
        with self.assertRaisesRegex(TransitionNotAllowed, 'active'):
            instance.wfm.transition(self.user_1, 2, self.user_3)
        self.user_3.is_active = True
        self.user_3.save()
        instance.wfm.transition(self.user_1, 2, self.user_3)


    def test_transition_user_notnull(self):
        instance = self.OkModel.objects.create()
        with self.assertRaisesRegex(TransitionNotAllowed, 'null'):
            instance.wfm.transition(None, 1, self.user_1)


    def test_transition_user_active(self):
        instance = self.OkModel.objects.create()
        self.user_1.is_active = False
        self.user_1.save()
        with self.assertRaisesRegex(TransitionNotAllowed, 'active'):
            instance.wfm.transition(self.user_1, 1, self.user_1)


    def test_transition_allowed_groups(self):
        instance_1 = self.OkModel.objects.create()
        instance_1.wfm.transition(self.user_1, 1, self.user_1)
        instance_1.wfm.transition(self.user_1, 2, self.user_4)
        instance_1.wfm.transition(self.user_4, 4, self.user_3)
        with self.assertRaisesRegex(TransitionNotAllowed, 'users.*from.*group4.*allowed'):
            instance_1.wfm.transition(self.user_3, 0, None)
        instance_1.wfm.transition(self.user_3, 4, self.user_4)
        instance_1.wfm.transition(self.user_4, 0, None)



    def test_state_constraints_prev_state(self):
        instance = self.OkModel.objects.create()
        instance.wfm.transition(self.user_1, 1, self.user_1)
        state2 = instance.wfm.transition(self.user_1, 2, self.user_3)

        with self.assertRaisesRegex(IntegrityError, '(UNIQUE|duplicat).*previous_state_id'):
            state2.pk = None
            state2.save()

    def test_state_constraints_next_state(self):
        instance = self.OkModel.objects.create()
        instance.wfm.transition(self.user_1, 1, self.user_1)
        state2 = instance.wfm.transition(self.user_1, 2, self.user_3)
        state1 = state2.previous_state

        with self.assertRaisesRegex(IntegrityError, '(UNIQUE|duplicat).*next_state_id'):
            state1.pk = None
            state1.save()


    def test_state_next_previous(self):
        instance = self.OkModel.objects.create()
        state1 = instance.wfm.transition(self.user_1, 1, self.user_1)
        state2 = instance.wfm.transition(self.user_1, 2, self.user_3)
        state1 = State.objects.get(pk=state1.pk)

        self.assertEqual(state1.previous_state, None)
        self.assertEqual(state1.next_state.pk, state2.pk)
        self.assertEqual(state2.next_state, None)
        self.assertEqual(state2.previous_state.pk, state1.pk)


    def test_current_state(self):
        instance = self.OkModel.objects.create()
        self.assertEqual(instance.wfm_state, None)
        self.assertEqual(instance.current_state, None)

        state = instance.wfm.transition(self.user_1, 1, self.user_1)
        self.assertEqual(state.phase, '1')
        self.assertEqual(state, instance.current_state)
        self.assertEqual(state, instance.wfm_state)

        state = instance.reload_current_state()
        self.assertEqual(state, instance.current_state)

        state = instance.wfm.transition(self.user_1, 2, self.user_3)
        self.assertEqual(state.phase, '2')
        self.assertEqual(state, instance.current_state)


    def test_state_get_instance_cached(self):
        instance = self.OkModel.objects.create()
        instance.wfm.transition(self.user_1, 1, self.user_1)
        # Reload from DB
        instance = self.OkModel.objects.get(pk=instance.pk)
        with self.assertNumQueries(1):
            state = instance.current_state
        # calling current_state property caches state.instance
        with self.assertNumQueries(0):
            inst = state.get_instance()
        self.assertEqual(instance.pk, inst.pk)


    def test_state_get_instance_not_cached(self):
        instance = self.OkModel.objects.create()
        instance.wfm.transition(self.user_1, 1, self.user_1)
        # Reload from DB
        instance = self.OkModel.objects.get(pk=instance.pk)
        with self.assertNumQueries(1):
            state = instance.wfm_state
        with self.assertNumQueries(1):
            inst = state.get_instance()
        self.assertEqual(instance.pk, inst.pk)



    def test_previous_state(self):
        instance = self.OkModel.objects.create()
        state1 = instance.wfm.transition(self.user_1, 1, self.user_1)
        state2 = instance.wfm.transition(self.user_1, 2, self.user_3)
        with self.assertNumQueries(0):
            prv = state2.previous_state
            self.assertEqual(state1.pk, prv.pk)
        with self.assertNumQueries(1):
            state2new = instance.reload_current_state()
        with self.assertNumQueries(1):
            prv = state2new.previous_state
            self.assertEqual(state1.pk, prv.pk)


    def test_previous_different_state(self):
        instance = self.OkModel.objects.create()
        st1 = instance.wfm.transition(self.user_1, 1, self.user_1)
        st3 = instance.wfm.transition(self.user_1, 2, self.user_3)
        st4 = instance.wfm.transition(self.user_3, 2, self.user_4)
        st5 = instance.wfm.transition(self.user_4, 3, None)
        self.assertEqual(st4.get_previous_different_state(), '1')
        self.assertEqual(st5.get_previous_different_state(), '2')

        self.assertEqual(st5.find_last_state('2'), st4)
        self.assertEqual(st4.find_last_state('2'), st3)
        self.assertEqual(st5.find_last_state('1'), st1)
        self.assertEqual(st3.find_last_state('1'), st1)


    def test_materialized_wfm_state(self):
        instance = self.OkModel.objects.create()
        state = instance.wfm.transition(self.user_1, 1, self.user_1)
        self.assertEqual(state.phase, '1')
        # Instance.wfm_state is assigned by transition
        with self.assertNumQueries(0):
            self.assertEqual(state, instance.wfm_state)
            self.assertEqual(state, instance.current_state)
        self.assertEqual(instance.states.all().count(), 1)

        with self.assertNumQueries(1):
            state = instance.reload_current_state()
            self.assertEqual(state, instance.wfm_state)

        state = instance.wfm.transition(self.user_1, 2, self.user_3)
        self.assertEqual(state.phase, '2')
        self.assertEqual(state, instance.wfm_state)

        with self.assertNumQueries(1):
            inst2 = self.OkModel.objects.get(pk = instance.pk)
        with self.assertNumQueries(1):
            self.assertEqual(state, inst2.current_state)
            self.assertEqual(state.phase, inst2.current_state.phase)




    def test_current_state_str(self):
        # model.current_state_str(defa) in injected by WFM
        instance = self.OkModel.objects.create()
        self.assertEqual(instance.current_state_str(), '')
        self.assertEqual(instance.current_state_str('none'), 'none')
        self.assertEqual(instance.current_state_str(None), None)

        instance.wfm.transition(self.user_1, 1, self.user_1)
        self.assertEqual(instance.current_state_str(), '1')
        self.assertEqual(instance.current_state_str('anything'), '1')


    def test_states(self):
        # model.states generic relation is injected by WFM

        instance = self.OkModel.objects.create()
        state1 = instance.wfm.transition(self.user_1, 1, self.user_1)
        state2 = instance.wfm.transition(self.user_1, 2, self.user_3)

        self.assertEqual(instance.states.count(), 2)

        states_1 = instance.states.get(phase='1')
        self.assertEqual(states_1.pk, state1.pk)

        states_2 = instance.states.get(phase='2')
        self.assertEqual(states_2.pk, state2.pk)


    # 2 -> 4 has allow-reject = False
    def test_allow_reject(self):
        instance = self.OkModel.objects.create()
        instance.wfm.transition(self.user_4, 1, self.user_4)
        instance.wfm.transition(self.user_4, 2, self.user_4)
        instance.wfm.transition(self.user_4, 4, self.user_4)
        with self.assertRaisesRegex(TransitionNotAllowed, 'Unreachable'):
            instance.wfm.transition(self.user_4, 2, self.user_4)
        state = instance.wfm.transition(self.user_4, 1, self.user_4)
        self.assertEqual(state.phase, '1')

    def test_wfm_model_get_config(self):
        instance = self.OkModel.objects.create()
        config = instance.wfm_config
        self.assertEqual(config['2']['read'], [])

        cfm = self.OkModel.wfm_config
        self.assertEqual(config, cfm)


    def test_find_last_state(self):
        instance = self.OkModel.objects.create()
        instance.wfm.transition(self.user_1, 1, self.user_1)
        state1 = instance.wfm.transition(self.user_1, 2, self.user_3)
        instance.wfm.transition(self.user_3, 1, self.user_1)
        state2 = instance.wfm.transition(self.user_1, 2, self.user_3)
        instance.wfm.transition(self.user_3, 4, None)
        state = instance.wfm.transition(self.user_3, 4, self.user_3)

        self.assertEqual(state2, state.find_last_state('2'))
        self.assertEqual(state1, state2.find_last_state('2'))


    def test_after_state_transition(self):
        instance = self.OkModel.objects.create()
        self.assertFalse(hasattr(instance, 'transition_committed'))
        with transaction.atomic():
            instance.wfm.transition(self.user_1, 1, self.user_1)
            self.assertEqual(instance.transition_committed, 1)
            instance.wfm.transition(self.user_1, 2, self.user_3)
            self.assertEqual(instance.transition_committed, 2)
            instance.wfm.transition(self.user_3, 3, None)
            self.assertEqual(instance.transition_committed, 3)


    def test_transaction_rollback(self):
        instance = self.OkModel.objects.create()

        instance.invalid_2_to_3 = True
        with self.assertRaisesRegex(ValidationError, '2 to 3'):
            with transaction.atomic():
                instance.wfm.transition(self.user_1, 1, self.user_1)
                self.assertEqual(instance.transition_committed, 1)
                instance.wfm.transition(self.user_1, 2, self.user_3)
                self.assertEqual(instance.transition_committed, 2)
                instance.wfm.transition(self.user_3, 3, None)

        # Warning!!!! Object cached attributes remain dirty after rollback
        self.assertEqual(instance.current_state_str(), '2')
        self.assertEqual(instance.transition_committed, 2)
        # Re-read from DB
        self.assertEqual(instance.reload_current_state(), None)
        self.assertEqual(instance.states.count(), 0)


    def test_transaction_rollback_generic_handler(self):
        instance = self.OkModel.objects.create()
        with self.assertRaisesRegex(ValidationError, 'generic'):
            with transaction.atomic():
                instance.wfm.transition(self.user_1, 1, self.user_1)
                instance.wfm.transition(self.user_1, 2, self.user_3)
                self.assertEqual(instance.transition_committed, 2)
                instance.invalid_transition = True
                instance.wfm.transition(self.user_3, 3, None)
        self.assertEqual(instance.reload_current_state(), None)
        self.assertEqual(instance.states.count(), 0)



    def test_validate_transition_fail(self):
        instance = self.OkModel.objects.create()
        instance.invalid_1_to_2 = True
        instance.wfm.transition(self.user_1, 1, self.user_1)
        with self.assertRaises(ValidationError) as cm:
            instance.wfm.transition(self.user_1, 2, self.user_3)
        self.assertIn('1', str(cm.exception))

    def test_validate_transition_fail_any(self):
        instance = self.OkModel.objects.create()
        instance.invalid_any_to_2 = True
        instance.wfm.transition(self.user_1, 1, self.user_1)
        with self.assertRaises(ValidationError) as cm:
            instance.wfm.transition(self.user_1, 2, self.user_3)
        self.assertIn('any', str(cm.exception))


    def test_validate_transition_ok(self):
        instance = self.OkModel.objects.create()
        instance.wfm.transition(self.user_1, 1, self.user_1)
        instance.wfm.transition(self.user_1, 2, self.user_3)
        self.assertEqual(instance.current_state_str(), '2')


    def test_user_can_read(self):
        instance = self.OkModel.objects.create()
        with self.assertRaises(UnmanagedObject):
            instance.wfm.can_read(self.user_1)
        instance.wfm.transition(self.user_1, 1, self.user_1)
        self.assertTrue(instance.wfm.can_read(self.user_1))
        self.assertTrue(instance.wfm.can_read(self.user_2))
        self.assertTrue(instance.wfm.can_read(self.user_3))


    def test_user_take_ownership(self):
        instance = self.OkModel.objects.create()
        instance.wfm.transition(self.user_1, 1, self.user_1)

        self.assertFalse(instance.wfm.can_take_ownership(self.user_2))
        self.assertFalse(instance.wfm.can_take_ownership(self.user_1))
        self.assertFalse(instance.wfm.can_take_ownership(self.user_3))
        self.assertTrue(instance.wfm.can_take_ownership(self.user_4))

        instance.wfm.take_ownership(self.user_4)
        self.assertTrue(instance.wfm.can_take_ownership(self.user_1))

        instance.wfm.take_ownership(self.user_1)
        with self.assertNumQueries(0):
            self.assertEqual(self.user_1, instance.current_state.owner)


    def test_user_assign(self):
        instance = self.OkModel.objects.create()
        instance.wfm.transition(self.user_1, 1, self.user_1)

        st = instance.wfm.assign(self.user_2)
        self.assertEqual(st.user, self.user_1)
        self.assertEqual(st.owner, self.user_2)

        st = instance.wfm.assign(self.user_1, user=self.user_4)
        self.assertEqual(st.user, self.user_4)
        self.assertEqual(st.owner, self.user_1)


    def test_reject(self):
        instance = self.OkModel.objects.create()
        instance.wfm.transition(self.user_1, 1, self.user_1)
        state = instance.wfm.transition(self.user_1, 2, self.user_3)
        self.assertTrue(state.can_reject)
        state = instance.wfm.reject(self.user_3)

        self.assertEqual(state.phase, '1')
        self.assertEqual(state.transition_type, 'reject')
        state = instance.wfm.transition(self.user_1, 2, self.user_3)
        self.assertEqual(state.transition_type, 'resubmit')


    def test_reject_to_state(self):
        instance = self.OkModel.objects.create()
        state = instance.wfm.transition(self.user_1, 1, self.user_1)
        instance.wfm.transition(self.user_1, 2, self.user_3)
        instance.wfm.transition(self.user_3, 4, self.user_4)
        rej_state = instance.wfm.reject_to_state(self.user_4, '1')
        self.assertEqual(state.phase, rej_state.phase)
        self.assertEqual(state.owner, rej_state.owner)
        self.assertEqual(rej_state.transition_type, 'change_assign') # TODO mark as reject?


    def test_can_release(self):
        # state1 has default allow_release=strict
        instance = self.OkModel.objects.create()
        state = instance.wfm.transition(self.user_1, 1, self.user_1)
        # User2 is editor only of state 1
        state = instance.wfm.transition(self.user_1, 1, self.user_2)
        self.assertFalse(state.can_release)

        state = instance.wfm.transition(self.user_2, 1, self.user_4)
        # user_4 is admin of state 1 so he can release even after an assign
        self.assertTrue(state.can_release)

        instance2 = self.OkModel.objects.create()
        instance2.wfm.transition(self.user_1, 1, self.user_1)
        instance2.wfm.transition(self.user_1, 1, None)
        state = instance2.wfm.transition(self.user_1_b, 1, self.user_1_b)
        # Now we have a take, so it can be released
        self.assertTrue(state.can_release)



    def test_release_user(self):
        instance = self.OkModel.objects.create()
        instance.wfm.transition(self.user_1, 1, self.user_1)
        instance.wfm.transition(self.user_1, 2, self.user_3)
        # state 4: edit(3), admin(4)
        instance.wfm.transition(self.user_3, 4, None)
        state = instance.wfm.take_ownership(self.user_3_b)
        self.assertEqual(state.transition_type, 'take')
        self.assertTrue(state.can_release)
        state = instance.wfm.transition(self.user_3_b, 4, self.user_3)
        self.assertEqual(state.transition_type, 'delegate')
        self.assertEqual(state.owner, self.user_3)
        self.assertFalse(instance.wfm.can_admin(self.user_3))
        self.assertFalse(state.can_release)
        state = instance.wfm.reject(self.user_3)
        self.assertEqual(state.owner, self.user_3_b)
        self.assertFalse(instance.wfm.can_admin(self.user_3_b))
        self.assertTrue(state.can_release)


    def test_release(self):
        instance = self.OkModel.objects.create()
        # state 1: admin(1, 4), edit(2)
        instance.wfm.transition(self.user_1, 1, self.user_1)
        state = instance.wfm.transition(self.user_1, 1, self.user_2)
        self.assertFalse(state.can_release)
        state = instance.wfm.reject(self.user_2)
        self.assertTrue(state.can_release)
        state = instance.wfm.transition(self.user_1, 1, self.user_4)
        self.assertTrue(state.can_release)
        state = instance.wfm.release(self.user_4)
        self.assertEqual(state.transition_type, 'release')
        self.assertEqual(state.owner, None)
        state = instance.wfm.take_ownership(self.user_2)
        self.assertEqual(state.transition_type, 'take')
        self.assertTrue(state.can_release)
        self.assertEqual(state.owner, self.user_2)
        with self.assertRaisesRegex(TransitionNotAllowed, 'null'):
            # 'allow_release'=no in state 2 blocks also 'change' transitions
            instance.wfm.transition(self.user_2, 2, None)
        # only 'chenge_assign' is allowed for state 2
        state = instance.wfm.transition(self.user_2, 2, self.user_4)
        # user4 is admin but in state 2 we can't release
        self.assertFalse(state.can_release)


    def test_assign(self):
        instance = self.OkModel.objects.create()

        instance.wfm.transition(self.user_1, 1, self.user_1)
        with self.assertRaisesRegex(TransitionNotAllowed, 'must be owner or admin'):
            instance.wfm.transition(self.user_2, 1, self.user_1_b)

        instance.wfm.release(self.user_1)
        with self.assertRaisesRegex(TransitionNotAllowed, 'must be admin'):
            instance.wfm.transition(self.user_2, 1, self.user_1_b)

        status = instance.wfm.transition(self.user_1, 1, self.user_2)
        self.assertEqual(status.transition_type, 'assign')


    def test_get_candidates(self):
        instance = self.OkModel.objects.create()
        instance.wfm.transition(self.user_1, 1, self.user_1)
        admin_candidates = self.OkModel.wfm_config.get_candidate_users_for_state('1', 'a')
        self.assertEqual(len(admin_candidates), 3)
        self.assertTrue(self.user_1 in admin_candidates and self.user_4 in admin_candidates)
        self.user_4.is_active = False
        self.user_4.save()
        admin_candidates =  self.OkModel.wfm_config.get_candidate_users_for_state('1', 'a', True)
        self.assertEqual(len(admin_candidates), 2)
        self.assertTrue(self.user_1 in admin_candidates)

        # 'e': edit only; 'ea' : edit or admin
        edit_candidates =  self.OkModel.wfm_config.get_candidate_users_for_state('1', 'e')
        self.assertEqual(len(edit_candidates), 1)
        self.assertTrue(self.user_2 in edit_candidates)


    def test_get_custom_candidates(self):
        instance = self.OkModel.objects.create()
        instance.wfm.transition(self.user_1, 1, self.user_1)
        instance.exclude_group4 = True
        admin_candidates = instance.get_candidate_users('1', 'a')
        self.assertEqual(len(admin_candidates), 2)
        self.assertFalse(self.user_4 in admin_candidates)


    def test_get_administrable_states_for_model(self):
        adm_states = self.OkModel.wfm_config.get_states_for_permissions(self.user_1, 'a')
        self.assertEqual(adm_states, ['1'])

        adm_states = self.OkModel.wfm_config.get_states_for_permissions(self.user_4, 'a')
        self.assertCountEqual(adm_states, ['1', '2', '4'])


    def test_get_editable_states_for_model(self):
        ed_states = self.OkModel.wfm_config.get_states_for_permissions(self.user_1, 'ea')
        self.assertEqual(ed_states, ['1'])

        ed_states = self.OkModel.wfm_config.get_states_for_permissions(self.user_3, 'ea')
        self.assertCountEqual(ed_states, ['2', '4'])


    def test_get_viewable_states_for_model(self):
        view_states = self.OkModel.wfm_config.get_states_for_permissions(self.user_1, 'rea')
        self.assertEqual(view_states, ['1'])

        view_states = self.OkModel.wfm_config.get_states_for_permissions(self.user_3, 'rea')
        self.assertCountEqual(view_states, ['1', '2', '4'])


    def test_transition_type(self):
        instance_1 = self.OkModel.objects.create()

        #tell the workflow that instance was created by user_1
        state = instance_1.wfm.transition(self.user_1, 1, self.user_1)
        self.assertEqual(state.transition_type, 'new')

        #free record
        state = instance_1.wfm.transition(self.user_1, 1, None)
        self.assertEqual(state.transition_type, 'release')

        state = instance_1.wfm.transition(self.user_1, 1, self.user_1)
        self.assertEqual(state.transition_type, 'take')


        #delegating instance to user_2
        state = instance_1.wfm.transition(self.user_1, 1, self.user_2)
        self.assertEqual(state.transition_type, 'delegate')

        #rejecting instance_1
        state = instance_1.wfm.transition(self.user_2, 1, self.user_1)
        self.assertEqual(state.transition_type, 'reject')

        #delegating again instance to user_2
        state = instance_1.wfm.transition(self.user_1, 1, self.user_2, force_transition_type='delegate')
        # Would be resubmit
        self.assertEqual(state.transition_type, 'delegate')

        # Now set to delegate instance_1
        state = instance_1.wfm.transition(self.user_2, 1, self.user_1, force_transition_type='delegate')
        # Would be reject
        self.assertEqual(state.transition_type, 'delegate')

        #change state
        state = instance_1.wfm.transition(self.user_1, 2, self.user_3)
        self.assertEqual(state.transition_type, 'change_assign')

        #snatch record
        state = instance_1.wfm.transition(self.user_4, 2, self.user_4)
        self.assertEqual(state.transition_type, 'snatch')

        # change status
        state = instance_1.wfm.transition(self.user_4, 4, None)
        self.assertEqual(state.transition_type, 'change')

        state = instance_1.wfm.transition(self.user_4, 4, self.user_3)
        self.assertEqual(state.transition_type, 'assign')

        #Bug #235
        instance_2 = self.OkModel.objects.create()
        state = instance_2.wfm.transition(self.user_4, 1, self.user_4)
        state = instance_2.wfm.transition(self.user_4, 2, self.user_3)
        state = instance_2.wfm.transition(self.user_4, 2, self.user_4)
        self.assertEqual(state.transition_type, 'snatch')



    def test_transition_type_assign(self):
        instance_1 = self.OkModel.objects.create()

        # assign record, Admin only: from None to new user; reject -> back to user (Admin)
        instance_1.wfm.transition(self.user_1, 1, self.user_1)
        instance_1.wfm.release(self.user_1)
        state = instance_1.wfm.transition(self.user_1, 1, self.user_2)
        self.assertEqual(state.transition_type, 'assign')
        self.assertTrue(state.can_reject)

        state = instance_1.wfm.transition(self.user_2, 1, self.user_1)
        self.assertEqual(state.transition_type, 'reject')


    def test_transition_type_assign_fail(self):
        instance_1 = self.OkModel.objects.create()

        instance_1.wfm.transition(self.user_1, 1, self.user_1)
        instance_1.wfm.release(self.user_1)
        with self.assertRaisesRegex(TransitionNotAllowed, 'must be admin'):
            instance_1.wfm.transition(self.user_2, 1, self.user_1)
        instance_1.wfm.take_ownership(self.user_1)
        instance_1.wfm.transition(self.user_1, 2, self.user_3)

        # Only admin can assign records
        with self.assertRaisesRegex(TransitionNotAllowed, 'must be owner or admin'):
            instance_1.wfm.transition(self.user_3_b, 2, self.user_3_c)


    def test_transition_type_reassign(self):
        instance_1 = self.OkModel.objects.create()

        # reassign record (Admin: from user1 to user2; reject -> back to user(admin))
        instance_1.wfm.transition(self.user_1, 1, self.user_1)
        instance_1.wfm.transition(self.user_1, 2, self.user_3)
        instance_1.wfm.transition(self.user_4, 2, self.user_3_b)
        state = instance_1.reload_current_state()
        self.assertEqual(state.transition_type, 'reassign')
        self.assertTrue(state.can_reject)

        instance_1.wfm.transition(self.user_3_b, 2, self.user_4)
        state = instance_1.reload_current_state()
        self.assertEqual(state.transition_type, 'reject')


    def test_transition_type_change_assign(self):
        instance_1 = self.OkModel.objects.create()

        # reassign record (Admin: from user1 to user2; reject -> back to user(admin))
        state = instance_1.wfm.transition(self.user_4, 1, self.user_4)
        self.assertEqual(state.transition_type, 'new')
        state = instance_1.wfm.transition(self.user_4, 2, self.user_4)
        self.assertEqual(state.transition_type, 'change_assign')
        state = instance_1.wfm.transition(self.user_4, 4, self.user_4)
        self.assertEqual(state.transition_type, 'change_assign')
        state = instance_1.wfm.transition(self.user_4, 1, self.user_4)
        self.assertEqual(state.transition_type, 'change_assign')


    def test_suspend_resume_user(self):
        instance = self.OkModel.objects.create()
        instance.wfm.transition(self.user_1, 1, self.user_1)
        state = instance.wfm.transition(self.user_1, 1, self.user_1, suspended=True)
        self.assertTrue(state.suspended)
        self.assertEqual(state.transition_type, 'suspend')
        self.assertFalse(state.can_release)

        with self.assertRaises(TransitionNotAllowed):
            instance.wfm.transition(self.user_1, 2, self.user_3)

        with self.assertRaises(TransitionNotAllowed):
            state = instance.wfm.transition(self.user_1, 1, self.user_1, suspended=True)

        state = instance.wfm.transition(self.user_1, 1, self.user_1, suspended=False)
        self.assertFalse(state.suspended)
        self.assertEqual(state.transition_type, 'resume')
        self.assertTrue(state.can_release)


    def test_suspend_resume_helper(self):
        instance = self.OkModel.objects.create()
        instance.wfm.transition(self.user_1, 1, self.user_1)
        state = instance.wfm.transition(self.user_1, 1, self.user_1, suspended=True)
        self.assertTrue(state.suspended)
        self.assertEqual(state.transition_type, 'suspend')

        with self.assertRaises(TransitionNotAllowed):
            instance.wfm.transition(self.user_1, 2, self.user_3)

        with self.assertRaises(TransitionNotAllowed):
            state = instance.wfm.transition(self.user_1, 1, self.user_1, suspended=True)

        state = instance.wfm.transition(self.user_1, 1, self.user_1, suspended=False)
        self.assertFalse(state.suspended)
        self.assertEqual(state.transition_type, 'resume')

    def test_suspend_resume_admin(self):
        instance = self.OkModel.objects.create()
        instance.wfm.transition(self.user_1, 1, self.user_1)
        state = instance.wfm.transition(self.user_1, 1, self.user_1, suspended=True)
        state = instance.wfm.transition(self.user_4, 1, self.user_4, suspended=False)
        self.assertFalse(state.suspended)
        self.assertEqual(state.transition_type, 'snatch')


    def test_unread(self):
        instance = self.OkModel.objects.create()
        state = instance.wfm.transition(self.user_1, 1, self.user_1)
        self.assertFalse(state.unread)
        state = instance.wfm.transition(self.user_4, 1, self.user_4)
        self.assertFalse(state.unread)
        state = instance.wfm.transition(self.user_4, 1, self.user_1)
        self.assertTrue(state.unread)
        state = instance.wfm.transition(self.user_1, 1, None)
        self.assertFalse(state.unread)




    def test_wfm_model_injected_methods(self):
        instance_1 = self.OkModel.objects.create()

        self.assertTrue(instance_1.wfm.transition_allowed(self.user_1, 1, self.user_1))
        state = instance_1.wfm.transition(self.user_1, 1, self.user_1)
        self.assertEqual(state.phase, '1')
        self.assertEqual(state.owner, self.user_1)

        state = instance_1.wfm.transition(self.user_1, 1, None)
        self.assertEqual(state.owner, None)
        self.assertEqual(state.phase, '1')
        self.assertEqual(instance_1.current_state_str(), '1')
        self.assertEqual(instance_1.current_state.phase, '1')

        state = instance_1.wfm.take_ownership(self.user_4)
        self.assertEqual(state.owner, self.user_4)

        # Take ownership returns current state if user is already owner
        new_state = instance_1.wfm.take_ownership(self.user_4)
        self.assertEqual(new_state.pk, state.pk)





    ####################################################################
    # TransitionDescriptor tests

    def test_td_validate_transition_fail(self):
        instance = self.OkModel.objects.create()
        instance.invalid_1_to_2 = True
        tex = instance.wfm.get_transition(1, self.user_1, self.user_1)
        tex.execute()
        t =  instance.wfm.get_transition(2, self.user_1, self.user_3)
        self.assertTrue(not t.allowed())
        with self.assertRaises(ValidationError):
            t.execute()

    def test_td_validate_transition_ok(self):
        instance = self.OkModel.objects.create()
        instance.wfm.get_transition(1, self.user_1, self.user_1).execute()
        t = instance.wfm.get_transition(2, self.user_1, self.user_3)
        state = t.execute()
        self.assertEqual(state.phase, '2')


    def test_td_reject(self):
        instance = self.OkModel.objects.create()
        instance.wfm.get_transition(1, self.user_1, self.user_1).execute()
        state = instance.wfm.get_transition(2, self.user_1, self.user_3).execute()
        self.assertTrue(state.can_reject)

        state = instance.wfm.get_transition('reject', self.user_3).execute()
        self.assertEqual(state.phase, '1')
        self.assertEqual(state.transition_type, 'reject')


    def test_td_release(self):
        instance = self.OkModel.objects.create()
        instance.wfm.get_transition(1, self.user_1, self.user_1).execute()
        state = instance.wfm.get_transition('release', self.user_1).execute()
        self.assertEqual(state.phase, '1')
        self.assertEqual(state.transition_type, 'release')
        self.assertEqual(state.owner, None)


    def test_td_properties(self):
        instance = self.OkModel.objects.create()
        instance.wfm.get_transition(1, self.user_1, self.user_1).execute()
        transition = instance.wfm.get_transition(2, self.user_1, self.user_3)
        self.assertEqual(transition.is_reject, False)
        self.assertEqual(transition.is_suspend, False)
        self.assertEqual(transition.is_resume, False)
        self.assertEqual(transition.transition, '1_to_2')
        self.assertEqual(transition.destination, '2')
        self.assertEqual(transition.phase_str, '1')
        self.assertEqual(transition.caption, 'exec 12')

        self.assertTrue(transition.is_forward)
        self.assertFalse(transition.is_backward)
        self.assertFalse(transition.is_free)
        self.assertFalse(transition.is_take_ownership)
        self.assertFalse(transition.is_hidden)
        self.assertFalse(transition.is_reject)
        self.assertFalse(transition.require_message)
        self.assertEqual(transition.destination_owner_mode, 'none')

        self.assertTrue(transition.allowed())
        state = transition.execute()
        self.assertTrue(state.can_reject)

    # Test signals
    def test_signal_transition_done(self):

        transition_done.connect(_transition_done_handler)
        instance_1 = self.OkModel.objects.create()
        st1 = instance_1.wfm.transition(self.user_1, 1, self.user_1)
        self.assertEqual(instance_1.pk, _tdd['instance'].pk)
        self.assertEqual(None, _tdd['prev_state'])
        self.assertEqual(st1.pk, _tdd['cur_state'].pk)

        st2 = instance_1.wfm.transition(self.user_1, 2, self.user_3)
        self.assertEqual(instance_1.pk, _tdd['instance'].pk)
        self.assertEqual(st1.pk, _tdd['prev_state'].pk)
        self.assertEqual(st2.pk, _tdd['cur_state'].pk)


    def test_long_message(self):
        instance = self.OkModel.objects.create()
        long_message = 'This is a very long message. ' * 10000
        instance.wfm.transition(self.user_1, 1, self.user_1, long_message)
        state = instance.reload_current_state()
        self.assertEqual(state.message, long_message)


    # Concurrency & other issues

    def test_concurrent_transition(self):
        inst1 = self.OkModel.objects.create()
        state1_1 = inst1.wfm.transition(self.user_1, 1, self.user_1)

        # Simulate concurrency with two instances pointing to the same object
        # TODO we need multithreading test
        #
        inst2 = self.OkModel.objects.get(pk=inst1.pk)
        state2_1 = inst2.current_state
        self.assertEqual(state2_1.pk, state1_1.pk)

        state1_2 = inst1.wfm.transition(self.user_1, 2, self.user_3)
        state2_1 = inst2.current_state
        self.assertEqual(state2_1.pk, state1_1.pk)

        # Must reload, has been changed by inst1
        state2_2 = inst2.reload_current_state()
        self.assertEqual(state2_2.pk, state1_2.pk)

        state1_3 = inst1.wfm.take_ownership(self.user_4)
        st = inst1.wfm_state #get_last_state()
        self.assertEqual(st.phase, '2')
        self.assertEqual(st.owner, self.user_4)
        self.assertEqual(st.pk, state1_3.pk)

        with self.assertRaises(StaleObject):
            inst2.wfm.take_ownership(self.user_3_b)
        inst2 = inst2.reload_from_db()
        with self.assertRaises(TransitionNotAllowed):
            inst2.wfm.take_ownership(self.user_3_b)


    #TODO move in class WFTransitionDescriptorTest(WorkflowTest):
    def test_allowed_groups_trans_enabled(self):
        inst = self.OkModel.objects.create()
        inst.wfm.transition(self.user_1, 1, self.user_1)
        inst.wfm.transition(self.user_1, 2, self.user_4)
        inst.wfm.transition(self.user_4, 4, self.user_3)
        trans = WFTransitionDescriptor(inst, 0, self.user_3)
        self.assertEqual(trans.allowed_groups, ['group4'])
        self.assertTrue(trans.is_disabled)
        inst.wfm.transition(self.user_3, 4, self.user_4)
        trans = WFTransitionDescriptor(inst, 0, self.user_4)
        self.assertFalse(trans.is_disabled)
        inst.wfm.transition(self.user_4, 0, None)


