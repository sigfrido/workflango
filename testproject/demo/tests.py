import io

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from workflango.mixins_tests import COMMON_PASSWORD, GUITestMixin, WorkflowTestMixin
from workflango.user_groups import init_all_groups, user_group_add

from .middleware import IMPERSONATE_SESSION_KEY
from .models import Request, Supplier


class DemoWorkflowTests(GUITestMixin, WorkflowTestMixin, TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        init_all_groups()
        User = get_user_model()
        cls.manager1 = User.objects.create_user('manager1', password=COMMON_PASSWORD)
        user_group_add(cls.manager1, 'MANAGERS')
        cls.user1 = User.objects.create_user('user1', password=COMMON_PASSWORD)
        user_group_add(cls.user1, 'USERS')

    def make_active_supplier(self):
        """Creates a Supplier and pushes it straight to 'active' via the workflow API
        (bypassing the GUI), as a fixture for tests that aren't about supplier creation."""
        supplier = Supplier.objects.create(company_name='Acme Corp', tax_code='ACME12345')
        supplier.wfm.transition(self.user1, 'proposed', self.user1)
        supplier.wfm.transition(self.manager1, 'proposed', self.manager1, message='taking over')  # manager takes ownership
        supplier.wfm.transition(self.manager1, 'active', self.manager1)
        return supplier

    def test_create_supplier_via_gui(self):
        self.login('user1')
        response = self.post_view(reverse('supplier_create'), {
            'company_name': 'New Supplier', 'tax_code': 'NEWSUP123',
        })
        self.assertEqual(response.status_code, 200)
        supplier = Supplier.objects.get(company_name='New Supplier')
        self.assertEqual(supplier.current_state.phase, 'proposed')
        self.assertEqual(supplier.current_state.owner, self.user1)

    def test_only_manager_can_activate_supplier(self):
        supplier = Supplier.objects.create(company_name='Beta Ltd', tax_code='BETA12345')
        supplier.wfm.transition(self.user1, 'proposed', self.user1)

        self.login('user1')
        url = reverse('supplier_change_state', kwargs={'pk': supplier.pk, 'destination_phase': 'active'})
        self.post_view(url, {})
        supplier = self.reload_inst(supplier)
        self.assertEqual(supplier.current_state.phase, 'proposed')  # unchanged: user1 is not a manager

    def test_manager_activates_supplier(self):
        supplier = Supplier.objects.create(company_name='Gamma Srl', tax_code='GAMMA1234')
        supplier.wfm.transition(self.user1, 'proposed', self.user1)

        self.login('manager1')
        take_url = reverse('supplier_change_state', kwargs={'pk': supplier.pk, 'destination_phase': 'take-ownership'})
        self.post_view(take_url, {'message': 'Manager taking over to activate.'})
        supplier = self.reload_inst(supplier)
        self.assertEqual(supplier.current_state.owner, self.manager1)

        # manager1 is an 'admin' at 'proposed', so the form makes them pick an explicit
        # destination owner rather than guessing -- assign it to themselves.
        activate_url = reverse('supplier_change_state', kwargs={'pk': supplier.pk, 'destination_phase': 'active'})
        self.post_view(activate_url, {'owner': self.manager1.pk})
        supplier = self.reload_inst(supplier)
        self.assertEqual(supplier.current_state.phase, 'active')

    def test_request_cannot_target_non_active_supplier(self):
        proposed_supplier = Supplier.objects.create(company_name='Delta SpA', tax_code='DELTA1234')
        proposed_supplier.wfm.transition(self.user1, 'proposed', self.user1)

        self.login('user1')
        response = self.post_view(reverse('request_create'), {
            'title': 'Should fail', 'description': '', 'budget': '100.00',
            'supplier': proposed_supplier.pk,
        }, follow=False)
        self.assertEqual(response.status_code, 200)  # form re-rendered with errors, no redirect
        self.assertFalse(Request.objects.filter(title='Should fail').exists())

    def test_request_full_flow_and_editable_fields(self):
        supplier = self.make_active_supplier()

        self.login('user1')
        self.post_view(reverse('request_create'), {
            'title': 'Buy widgets', 'description': 'some widgets', 'budget': '500.00',
            'supplier': supplier.pk,
        })
        req = Request.objects.get(title='Buy widgets')
        self.assertEqual(req.current_state.phase, 'draft')
        self.assertEqual(req.current_state.owner, self.user1)

        # Regression check for a name collision: Request's default context_object_name
        # ('request') used to shadow the real HttpRequest in the shipped workflow
        # templates, so `request.user` silently resolved to '' and every `{% if
        # request.user == ... %}` in workflow_buttons.html/workflow_edit_btn.html came
        # up empty -- no transition buttons, and the edit button rendered caption "None"
        # (missing 'edit_button_label') instead of "Edit". See _RequestObjectNameMixin.
        detail_response = self.get_view(req.get_absolute_url())
        self.assertContains(detail_response, f'{req.get_change_state_url("submitted")}')
        self.assertContains(detail_response, '>Submit<')
        self.assertContains(detail_response, '>Edit<')
        self.assertNotContains(detail_response, '>None<')

        # draft -> submitted
        submit_url = reverse('request_change_state', kwargs={'pk': req.pk, 'destination_phase': 'submitted'})
        self.post_view(submit_url, {})
        req = self.reload_inst(req)
        self.assertEqual(req.current_state.phase, 'submitted')

        # manager takes ownership, then approves
        self.login('manager1')
        take_url = reverse('request_change_state', kwargs={'pk': req.pk, 'destination_phase': 'take-ownership'})
        self.post_view(take_url, {'message': 'Manager taking over to review.'})
        req = self.reload_inst(req)
        self.assertEqual(req.current_state.owner, self.manager1)

        # while submitted (owned by manager1), only manager_notes/reference_code should
        # render as editable inputs; title should render as read-only text.
        edit_response = self.get_view(reverse('request_edit', kwargs={'pk': req.pk}))
        self.assertContains(edit_response, 'name="manager_notes"')
        self.assertNotContains(edit_response, 'name="title"')

        # 'approved' is a closed phase with no configured edit/admin groups, so the only
        # valid choice in the (still-shown, since manager1 is an admin at 'submitted')
        # owner dropdown is "---" (unassigned) -- '0' is that sentinel value.
        approve_url = reverse('request_change_state', kwargs={'pk': req.pk, 'destination_phase': 'approved'})
        self.post_view(approve_url, {'owner': '0'})
        req = self.reload_inst(req)
        self.assertEqual(req.current_state.phase, 'approved')

    def test_manager_can_take_ownership_of_a_draft_request_owned_by_another_user(self):
        # Regression: Request's 'draft' phase originally had no 'admin' override (unlike
        # Supplier's 'proposed', which does), so it fell back to workflow_defaults'
        # empty admin=[] -- manager1 wasn't 'admin' at 'draft', so can_admin() was False
        # and workflow_buttons.html's "Take ownership (ADMIN)" / "Reassign (ADMIN)"
        # branch never rendered for a request they didn't already own.
        supplier = self.make_active_supplier()
        request = Request.objects.create(title='Buy widgets', budget='500.00', supplier=supplier)
        request.wfm.transition(self.user1, 'draft', self.user1)

        self.login('manager1')
        response = self.get_view(request.get_absolute_url())
        self.assertTrue(request.wfm.can_admin(self.manager1))
        self.assertContains(response, f'{request.get_change_state_url("take-ownership")}')
        self.assertContains(response, 'Take ownership (ADMIN)')

    def test_anyone_can_view_supplier_regardless_of_phase_or_ownership(self):
        supplier = self.make_active_supplier()  # active, owned by manager1
        supplier.wfm.transition(self.manager1, 'archived', None)  # 'archived' has no edit/admin group at all

        for username in ('user1', 'manager1'):
            self.login(username)
            response = self.get_view(supplier.get_absolute_url())
            self.assertEqual(response.status_code, 200, f'{username} should be able to view an archived supplier')

    def _activate_supplier(self, company_name, tax_code):
        """Like make_active_supplier(), but with a caller-chosen name/tax_code."""
        supplier = Supplier.objects.create(company_name=company_name, tax_code=tax_code)
        supplier.wfm.transition(self.user1, 'proposed', self.user1)
        supplier.wfm.transition(self.manager1, 'proposed', self.manager1, message='taking over')
        supplier.wfm.transition(self.manager1, 'active', self.manager1)
        return supplier

    def test_supplier_list_owner_filter_blank_vs_explicit_none(self):
        # Regression: search_wf_owner left blank must mean "no owner filter",
        # distinct from explicitly selecting owner "None" ('none' in USER_CHOICES,
        # meaning "owner is null") -- making WorkflowFilterForm's fields required=False
        # (so the browser stops blocking submission of an unfilled filter) must not
        # blur this.
        owned = self.make_active_supplier()  # owned by manager1
        unowned = self._activate_supplier('Empty Co', 'EMPTY6789')
        unowned.current_state.owner = None
        unowned.current_state.save(update_fields=['owner'])

        self.login('user1')
        response = self.get_list_view(Supplier, data={})
        self.assertCountEqual([s.pk for s in response.context['object_list']], [owned.pk, unowned.pk])

        response = self.get_list_view(Supplier, data={'search_wf_owner': 'none'})
        self.assertEqual([s.pk for s in response.context['object_list']], [unowned.pk])

    def test_supplier_list_filters_by_name_and_tax_code(self):
        acme = self.make_active_supplier()  # 'Acme Corp' / 'ACME12345'
        other = self._activate_supplier('Other Co', 'OTHER6789')

        self.login('user1')
        response = self.get_list_view(Supplier, data={'search_name': 'Acme'})
        self.assertEqual([s.pk for s in response.context['object_list']], [acme.pk])

        response = self.get_list_view(Supplier, data={'search_tax_code': 'OTHER'})
        self.assertEqual([s.pk for s in response.context['object_list']], [other.pk])

    def test_supplier_list_filters_by_has_requests(self):
        with_request = self.make_active_supplier()
        without_request = self._activate_supplier('Empty Co', 'EMPTY6789')
        req = Request.objects.create(title='Buy widgets', budget='100.00', supplier=with_request)
        req.wfm.transition(self.user1, 'draft', self.user1)

        self.login('user1')
        response = self.get_list_view(Supplier, data={'search_has_requests': 'True'})
        self.assertEqual([s.pk for s in response.context['object_list']], [with_request.pk])

        response = self.get_list_view(Supplier, data={'search_has_requests': 'False'})
        self.assertEqual([s.pk for s in response.context['object_list']], [without_request.pk])

    def test_request_list_filters_by_budget_min_and_supplier(self):
        supplier = self.make_active_supplier()
        other_supplier = self._activate_supplier('Other Co', 'OTHER6789')
        small = Request.objects.create(title='Small', budget='50.00', supplier=supplier)
        small.wfm.transition(self.user1, 'draft', self.user1)
        big = Request.objects.create(title='Big', budget='5000.00', supplier=other_supplier)
        big.wfm.transition(self.user1, 'draft', self.user1)

        self.login('user1')
        response = self.get_list_view(Request, data={'search_budget_min': '1000'})
        self.assertEqual([r.pk for r in response.context['object_list']], [big.pk])

        response = self.get_list_view(Request, data={'search_supplier': str(supplier.pk)})
        self.assertEqual([r.pk for r in response.context['object_list']], [small.pk])

    def test_request_list_combines_generic_and_custom_filters(self):
        supplier = self.make_active_supplier()
        req = Request.objects.create(title='Big', budget='5000.00', supplier=supplier)
        req.wfm.transition(self.user1, 'draft', self.user1)

        self.login('user1')
        response = self.get_list_view(Request, data={'search_budget_min': '1000', 'search_wf_phase': 'draft'})
        self.assertEqual([r.pk for r in response.context['object_list']], [req.pk])
        self.assertEqual(response.context['search_errors'], [])


class ImpersonationTests(GUITestMixin, WorkflowTestMixin, TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        init_all_groups()
        User = get_user_model()
        cls.admin = User.objects.create_superuser('admin', password=COMMON_PASSWORD)
        cls.manager1 = User.objects.create_user('manager1', password=COMMON_PASSWORD)
        user_group_add(cls.manager1, 'MANAGERS')
        cls.user1 = User.objects.create_user('user1', password=COMMON_PASSWORD)
        user_group_add(cls.user1, 'USERS')

    def test_non_superuser_cannot_start_or_stop_impersonation(self):
        self.login('manager1')
        self.assertEqual(self.get_view(reverse('impersonate_start')).status_code, 403)
        self.assertEqual(self.post_view(reverse('impersonate_stop'), {}).status_code, 403)

    def test_impersonable_users_exclude_self_and_superusers(self):
        self.login('admin')
        response = self.get_view(reverse('impersonate_start'))
        choices = list(response.context['form'].fields['user'].queryset)
        self.assertIn(self.user1, choices)
        self.assertIn(self.manager1, choices)
        self.assertNotIn(self.admin, choices)

    def test_admin_impersonates_and_stops(self):
        self.login('admin')
        self.post_view(reverse('impersonate_start'), {'user': self.user1.pk})
        self.assertEqual(self.client.session[IMPERSONATE_SESSION_KEY], self.user1.pk)

        # Every subsequent request now runs as user1 -- e.g. the navbar shows the real
        # admin's name with the impersonated target in parentheses (base.html).
        home = self.get_view(reverse('home'))
        self.assertInResponse(f'{self.admin.username} ({self.user1.username})', status_code=200, html=False)

        self.post_view(reverse('impersonate_stop'), {})
        self.assertNotIn(IMPERSONATE_SESSION_KEY, self.client.session)

    def test_transition_while_impersonating_records_impersonated_by(self):
        self.login('admin')
        self.post_view(reverse('impersonate_start'), {'user': self.user1.pk})

        # Created while impersonating user1: the object should be owned by user1 (the
        # impersonated identity), with the real admin recorded as impersonated_by.
        self.post_view(reverse('supplier_create'), {
            'company_name': 'Impersonated Co', 'tax_code': 'IMPCO12345',
        })
        supplier = Supplier.objects.get(company_name='Impersonated Co')
        self.assertEqual(supplier.current_state.owner, self.user1)
        self.assertEqual(supplier.current_state.user, self.user1)
        self.assertEqual(supplier.current_state.impersonated_by, self.admin)

    def test_edit_locked_until_admin_reclaims_ownership_then_locked_again_until_user_reclaims(self):
        """
        End-to-end mirror of GitHub issue #1's own example: an admin impersonating
        user1 cannot edit or transition a request user1 genuinely owns until they
        explicitly take ownership (a real, audited transition); genuine user1 is then
        locked out in turn until *they* reclaim it back.
        """
        supplier = Supplier.objects.create(company_name='Acme', tax_code='ACME12345')
        supplier.wfm.transition(self.manager1, 'proposed', self.manager1)
        supplier.wfm.transition(self.manager1, 'active', self.manager1)

        self.login('user1')
        self.post_view(reverse('request_create'), {
            'title': 'Buy widgets', 'description': '', 'budget': '100.00', 'supplier': supplier.pk,
        })
        request = Request.objects.get(title='Buy widgets')
        self.assertEqual(request.current_state.owner, self.user1)
        self.assertIsNone(request.current_state.impersonated_by)

        # --- Admin impersonates user1, BEFORE reclaiming ownership: locked out. ---
        self.login('admin')
        self.post_view(reverse('impersonate_start'), {'user': self.user1.pk})

        detail = self.get_view(request.get_absolute_url())
        self.assertFalse(detail.context['wf_editable'])
        self.assertNotContains(detail, '>Submit<')

        edit_response = self.get_view(reverse('request_edit', kwargs={'pk': request.pk}), follow=False)
        self.assertEqual(edit_response.status_code, 302)  # access denied -> redirected, not the form

        # --- Admin explicitly takes ownership while impersonating: a real, audited transition. ---
        take_url = reverse('request_change_state', kwargs={'pk': request.pk, 'destination_phase': 'take-ownership'})
        self.post_view(take_url, {})
        request = self.reload_inst(request)
        self.assertEqual(request.current_state.owner, self.user1)
        self.assertEqual(request.current_state.impersonated_by, self.admin)

        # --- Now editing/transitioning as admin-impersonating-user1 is offered and works. ---
        detail2 = self.get_view(request.get_absolute_url())
        self.assertTrue(detail2.context['wf_editable'])
        self.assertContains(detail2, '>Submit<')

        edit_response2 = self.get_view(reverse('request_edit', kwargs={'pk': request.pk}))
        self.assertEqual(edit_response2.status_code, 200)

        # --- Stop impersonating: genuine user1 is now locked out, symmetrically. ---
        self.post_view(reverse('impersonate_stop'), {})
        self.login('user1')

        detail3 = self.get_view(request.get_absolute_url())
        self.assertFalse(detail3.context['wf_editable'])
        self.assertNotContains(detail3, '>Submit<')

        edit_response3 = self.get_view(reverse('request_edit', kwargs={'pk': request.pk}), follow=False)
        self.assertEqual(edit_response3.status_code, 302)

        # --- Genuine user1 reclaims it back: normal access restored. ---
        self.post_view(take_url, {})
        request = self.reload_inst(request)
        self.assertEqual(request.current_state.owner, self.user1)
        self.assertIsNone(request.current_state.impersonated_by)

        detail4 = self.get_view(request.get_absolute_url())
        self.assertTrue(detail4.context['wf_editable'])
        self.assertContains(detail4, '>Submit<')

    def test_release_suspend_delegate_buttons_hidden_before_reclaim(self):
        """
        Regression: workflow_buttons.html's Release/Suspend/Delegate block was gated
        by a raw `st.owner == request.user` comparison, which -- unlike the
        `wf_editable`/`allowed_transitions` context vars -- was never made
        impersonation-aware. Since request.user is swapped to the impersonated target,
        that comparison was still (wrongly) true before an explicit reclaim, so these
        buttons rendered even though clicking them would (correctly) fail at
        transition_allowed(). Fixed with the `owned_by` template filter.
        """
        supplier = self.make_active_supplier()
        request = Request.objects.create(title='Buy widgets', budget='500.00', supplier=supplier)
        request.wfm.transition(self.user1, 'draft', self.user1)

        self.login('admin')
        self.post_view(reverse('impersonate_start'), {'user': self.user1.pk})

        detail = self.get_view(request.get_absolute_url())
        self.assertNotContains(detail, 'change-state/release/')
        self.assertNotContains(detail, 'change-state/suspend/')
        self.assertNotContains(detail, 'change-state/delegate/')
        self.assertContains(detail, 'change-state/take-ownership/')

        take_url = reverse('request_change_state', kwargs={'pk': request.pk, 'destination_phase': 'take-ownership'})
        self.post_view(take_url, {})

        detail2 = self.get_view(request.get_absolute_url())
        self.assertContains(detail2, 'change-state/release/')
        self.assertContains(detail2, 'change-state/suspend/')
        self.assertContains(detail2, 'change-state/delegate/')

    def make_active_supplier(self):
        supplier = Supplier.objects.create(company_name='Acme Corp', tax_code='ACME12345')
        supplier.wfm.transition(self.manager1, 'proposed', self.manager1)
        supplier.wfm.transition(self.manager1, 'active', self.manager1)
        return supplier


class ManagementCommandTests(TestCase):
    """
    Regression: check_wf_config/check_wf_objects declared a stale Django-1.x-style
    `args = '[<appname.model>, ...]'` class attribute, which modern argparse-based
    commands don't consult at all -- add_arguments() never declared a matching
    positional, so passing explicit model names on the command line failed with
    "unrecognized arguments" instead of scoping the check to just those models.
    """

    def test_check_wf_config_accepts_explicit_model_args(self):
        # Before the fix, argparse itself rejected the positional args ("unrecognized
        # arguments") before handle() ever ran -- both commands print via bare print()
        # rather than self.stdout.write(), so call_command's stdout= capture doesn't
        # see their output; not raising is the actual regression check.
        call_command('check_wf_config', 'demo.Supplier', 'demo.Request', stdout=io.StringIO())

    def test_check_wf_objects_accepts_explicit_model_args(self):
        call_command('check_wf_objects', 'demo.Supplier', stdout=io.StringIO())
