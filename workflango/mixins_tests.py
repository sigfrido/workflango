# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import datetime

from django.contrib.auth.models import User
from django.test.client import Client
from django.urls import reverse

from .user_groups import init_all_groups, user_group_add
from workflango import models as workflango_models

COMMON_PASSWORD = 'secret'


def listify(text_or_list):
    if isinstance(text_or_list, str) or not hasattr(text_or_list, '__iter__'):
        return (text_or_list, )
    return text_or_list


class WorkflowTestMixin(object):

    @classmethod
    def init_users(cls, users_dict, suffixes=[''], base_groups=[]):
        init_all_groups()
        User.objects.all().delete()
        workflango_models.WorkflowConfig.clear_cached_admins()

        cls.users = {None : None}
        for user_id in users_dict.keys():
            for suffix in suffixes:
                username = f'{user_id}{suffix}'
                email = f'{username}@test.it'
                cls.users[username] = User.objects.create_user(username, email, COMMON_PASSWORD)
                cls.users[username].save()
                for base_group in base_groups:
                    user_group_add(cls.users[username], base_group)
                for group in users_dict[user_id]:
                    user_group_add(cls.users[username], group)
                setattr(cls, f'user_{username}', cls.users[username])


    def str2date(self, strdate, date_format='%Y-%m-%d'):
        return datetime.datetime.strptime(strdate, date_format).date()


    # Begin test methods & helpers for single instance (obj)
    @property
    def obj(self):
        return self._obj

    def transition(self, user, new_state, owner, suspended=False, message=''):
        return self.obj.wfm.transition(self.users[user], new_state, self.users[owner], suspended=suspended, message=message)


    def transition_allowed(self, user, new_state, owner):
        return self.obj.wfm.transition_allowed(self.users[user], new_state, self.users[owner])


    def ok_transition(self, user, new_state, owner):
        state = self.transition(user, new_state, owner)
        self.assertEqual(state.phase, new_state)
        return state

    # End test methods single instance


    def assertIn(self, first, second, msg=None):
        for txt in listify(first):
            super(WorkflowTestMixin, self).assertIn(txt, second, msg)


    def reload_obj(self, *args):
        """
        Forces the reloading of one or more objects from DB. The objects are stored as properties in the TestCase object
        May throw an exception in self.name is not found
        """
        for obj_name in args:
            obj = getattr(self, obj_name)
            if not obj:
                raise KeyError(obj_name)
            obj = obj.__class__.objects.get(pk=obj.pk)
            setattr(self, obj_name, obj)


    def reload_inst(self, inst):
        return inst.__class__.objects.get(pk=inst.pk)



class GUITestMixin(object):

    MSG_ERR_CAMPO_OBBL = 'Campo obbligatorio.'

    @classmethod
    def setUpClass(cls):
        super(GUITestMixin, cls).setUpClass()
        cls.client = Client()

    """
    Try to grab TOTAL_FORMS and INITIAL_FORMS of inlines form
    in the current response context
    """
    def get_meta_formset_data(self):
        if 'inlines' not in self.response.context_data:
            return {}

        data = {}
        for inline in self.response.context_data['inlines']:
            prefix = inline.prefix
            data[prefix + "-TOTAL_FORMS"] = inline.total_form_count()
            data[prefix + "-INITIAL_FORMS"] = inline.initial_form_count()
        return data

    def login(self, username):
        self.client.logout()
        if not self.client.login(username=username, password=COMMON_PASSWORD):
            raise Exception(f"Impossibile loggare l'utente {username}.")
        return True


    def get_view(self, url, data={}, follow=True, **extra):
        self.response = self.client.get(url, data=data, follow=follow, **extra)
        return self.response


    def post_view(self, url, data={}, follow=True, **extra):
        self.response = self.client.post(url, data=data, follow=follow, **extra)
        return self.response


    def get_detail_view(self, instance, data={}):
        url = reverse(f'{instance.view_base_name}_detail', kwargs={'pk': instance.pk})
        return self.get_view(url, data=data)


    def get_list_view(self, model_or_inst, data={}):
        self.response = self.client.get(reverse(f'{model_or_inst.view_base_name}_list'), data=data, follow=True)
        return self.response


    def get_history_view(self, instance):
        self.response = self.client.get(reverse(f'{instance.view_base_name}_history', kwargs={'pk': instance.pk}), follow=True)
        return self.response


    def get_change_state_view(self, instance, state):
        self.response = self.client.get(
            reverse(f'{instance.view_base_name}_change_state', kwargs={'pk': instance.pk, 'nuovo_stato': state}),
            follow=True)
        return self.response


    def post_change_state_view(self, instance, state, owner=None, msg=None):
        data = {}
        if msg:
            data['message'] = msg
        if owner:
            data['owner'] = owner.id
        elif (state != instance.wfm_state.phase) or state in ('release', ):
            data['owner'] = 0
        return self.post_view(
            reverse(f'{instance.view_base_name}_change_state', kwargs={'pk': instance.pk, 'nuovo_stato': state}),
            data)


    def assertInResponse(self, text_or_list, status_code=200, html=False):
        for txt in listify(text_or_list):
            self.assertContains(self.response, text=txt, html=html, status_code=status_code)


    def assertNotInResponse(self, text_or_list, status_code=200, html=False):
        for txt in listify(text_or_list):
            self.assertNotContains(self.response, text=txt, html=html, status_code=status_code)


    def assertInMessages(self, text_or_list):
        messages = ';'.join([msg.message for msg in self.response.context['messages']])
        for txt in listify(text_or_list):
            self.assertIn(txt, messages)


    def assertNotInMessages(self, text_or_list):
        messages = ';'.join([msg.message for msg in self.response.context['messages']])
        for txt in listify(text_or_list):
            self.assertNotIn(txt, messages)


    def assertRedirectsToLogin(self, url):
        self.assertRedirects(self.response, f'{self.login_url()}?next={url}')


    def login_url(self):
        if not hasattr(self, '_login_url'):
            self._login_url = reverse('login')
        return self._login_url


    def assertWFMEditButton(self, visible, caption=''):
        """
        Test for the presence of an edit button indicator
        By default, only the icon is tested, caption may vary and negative tests can give false negatives
        """
        txt = f'<i class="icon-edit"></i>&nbsp;{caption}'
        if visible:
            self.assertInResponse(txt)
            self.assertTrue(self.response.context['wf_editable'])

        else:
            self.assertNotInResponse(txt)
            self.assertFalse(self.response.context['wf_editable'])


    def assertHasSelectOwner(self, is_present, allow_null=None):
        TXT_SELECT = '<select name="owner" id="id_owner">'
        TXT_NULL = '>---</option>'
        if is_present:
            self.assertContains(self.response, text=TXT_SELECT, html=False)
            if allow_null == True:
                self.assertContains(self.response, text=TXT_NULL, html=False)
            elif allow_null == False:
                self.assertNotContains(self.response, text=TXT_NULL, html=False)
        else:
            self.assertNotContains(self.response, text=TXT_SELECT, html=False)


    def addFormManagement(self, formdata, formname, initial, total):
        formdata[f'{formname}-INITIAL_FORMS'] = initial
        formdata[f'{formname}-MAX_NUM_FORMS'] = 1000
        formdata[f'{formname}-TOTAL_FORMS'] = total
        return formdata


    def addFormData(self, formdata, formname, instdata, instnum=None):
        if instnum == None:
            formdata.update(instdata)
        else:
            for k in instdata.keys():
                formdata[f'{formname}-{instnum}-{k}'] = instdata[k]
        return formdata



