# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from __future__ import print_function

from django.core.management.base import BaseCommand
from workflango.management.utils import get_model_list
from workflango.management.utils import send_email_to_admins

class Command(BaseCommand):

    args = '[<appname.model>, <appname.model>...]'
    help = 'Verifica lo stato del workflow per gli oggetti dei model specificati'

    def add_arguments(self, parser):
        parser.add_argument('--fix-stale-states', '-s', dest='fix_stale_states',
            action = 'store_true', default=False,
            help='Corregge automaticamente gli stati non aggiornati.')
        parser.add_argument('--fix-unmanaged-objects', '-u', dest='fix_unmanaged_objects',
            action = 'store_true', default=False,
            help='Corregge automaticamente le istanze senza stato.')

    CHECKS = (
        ('unmanaged_objects', 'istanze senza stato', ),
        ('stale_states', 'istanze con stato corrente non aggiornato'),
    )


    def handle(self, *args, **options):
        self.options = options
        self.errors = []
        for model in get_model_list(*args):
            self.check_model(model)
        if self.errors:
            subject = '[WebGPV] - check_wf_objects report'
            report = '\n'.join(self.errors)
            message = f'Report di esecuzione check_wf_message:\n{report}\n'
            send_email_to_admins(subject, message)
        for msg in self.errors:
            print(msg)


    def check_model(self, model):
        for (getter, fixer, autofix, er_msg) in self.get_checks():
            qset = getter(model)
            has_errors = False
            if qset.count():
                has_errors = True
                for inst in qset:
                    if autofix:
                        result = fixer(inst)
                        if result:
                            prefix = f'AUTOFIX ERR ({result})'
                        else:
                            prefix = 'AUTOFIX'
                    else:
                        prefix = 'ERR'
                    self.errors.append(f'{prefix}: {model.__name__} (pk={inst.pk}) - {er_msg}.')
        if not has_errors:
            print(f"OK: {model.__name__}")


    def get_checks(self):
        for (check_name, er_msg) in self.CHECKS:
            getter = getattr(self, f'get_{check_name}')
            fixer_name = f'fix_{check_name}'
            autofix = self.options.get(fixer_name, False)
            fixer = getattr(self, fixer_name)
            yield (getter, fixer, autofix, er_msg)

    def get_unmanaged_objects(self, model):
        return model.objects.filter(wfm_state__isnull=True)


    def fix_unmanaged_objects(self, obj):

        dest_state = obj.__class__.wfm_config.get_states_list()[0]
        admin = obj.__class__.wfm_config.admin()
        try:
            obj.wfm.transition(admin, dest_state, admin, message="Autofix unmanaged object")
            return ''
        except Exception as e:
            return str(e)


    def get_stale_states(self, model):
        return model.objects.filter(wfm_state__next_state__isnull=False)


    def fix_stale_states(self, obj):
        try:
            last_state = obj.states.all().order_by('-id')[0]
            obj.materialize_current_state(last_state)
            return ''
        except Exception as e:
            return str(e)





