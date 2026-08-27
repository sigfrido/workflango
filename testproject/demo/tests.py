from django.contrib.auth import get_user_model
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
        url = reverse('supplier_change_state', kwargs={'pk': supplier.pk, 'nuovo_stato': 'active'})
        self.post_view(url, {})
        supplier = self.reload_inst(supplier)
        self.assertEqual(supplier.current_state.phase, 'proposed')  # unchanged: user1 is not a manager

    def test_manager_activates_supplier(self):
        supplier = Supplier.objects.create(company_name='Gamma Srl', tax_code='GAMMA1234')
        supplier.wfm.transition(self.user1, 'proposed', self.user1)

        self.login('manager1')
        take_url = reverse('supplier_change_state', kwargs={'pk': supplier.pk, 'nuovo_stato': 'take-ownership'})
        self.post_view(take_url, {'message': 'Manager taking over to activate.'})
        supplier = self.reload_inst(supplier)
        self.assertEqual(supplier.current_state.owner, self.manager1)

        # manager1 is an 'admin' at 'proposed', so the form makes them pick an explicit
        # destination owner rather than guessing -- assign it to themselves.
        activate_url = reverse('supplier_change_state', kwargs={'pk': supplier.pk, 'nuovo_stato': 'active'})
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
        submit_url = reverse('request_change_state', kwargs={'pk': req.pk, 'nuovo_stato': 'submitted'})
        self.post_view(submit_url, {})
        req = self.reload_inst(req)
        self.assertEqual(req.current_state.phase, 'submitted')

        # manager takes ownership, then approves
        self.login('manager1')
        take_url = reverse('request_change_state', kwargs={'pk': req.pk, 'nuovo_stato': 'take-ownership'})
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
        approve_url = reverse('request_change_state', kwargs={'pk': req.pk, 'nuovo_stato': 'approved'})
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
