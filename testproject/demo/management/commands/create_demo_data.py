from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from workflango.user_groups import init_all_groups, user_group_add

from demo.models import Request, Supplier

DEMO_PASSWORD = 'demo12345'


class Command(BaseCommand):
    help = 'Creates the demo groups, accounts, and sample data (all with password "demo12345")'

    def handle(self, *args, **options):
        init_all_groups(verbose=True)
        User = get_user_model()

        admin, created = User.objects.get_or_create(username='admin', defaults={'is_superuser': True, 'is_staff': True})
        if created:
            admin.set_password(DEMO_PASSWORD)
            admin.save()
            self.stdout.write(self.style.SUCCESS('Created superuser: admin'))

        manager1, created = User.objects.get_or_create(username='manager1')
        if created:
            manager1.set_password(DEMO_PASSWORD)
            manager1.save()
            self.stdout.write(self.style.SUCCESS('Created user: manager1 (MANAGERS)'))
        user_group_add(manager1, 'MANAGERS')

        user1, created = User.objects.get_or_create(username='user1')
        if created:
            user1.set_password(DEMO_PASSWORD)
            user1.save()
            self.stdout.write(self.style.SUCCESS('Created user: user1 (USERS)'))
        user_group_add(user1, 'USERS')

        self.create_sample_data(manager1, user1)

        self.stdout.write(self.style.SUCCESS(f'Done. All demo accounts use password "{DEMO_PASSWORD}".'))

    def create_sample_data(self, manager1, user1):
        if Supplier.objects.exists() or Request.objects.exists():
            self.stdout.write('Sample suppliers/requests already exist, skipping.')
            return

        # Two suppliers proposed by user1 and left in their first phase, as requested.
        for name, tax_code in [('Acme Corp', 'ACME12345'), ('Beta Ltd', 'BETA12345')]:
            supplier = Supplier.objects.create(company_name=name, tax_code=tax_code)
            supplier.wfm.transition(user1, 'proposed', user1)
        self.stdout.write(self.style.SUCCESS('Created 2 sample suppliers (proposed, owned by user1).'))

        # A request needs an *active* supplier to target (Request.clean()), so one
        # more supplier is pushed all the way to 'active' by manager1 first.
        active_supplier = Supplier.objects.create(company_name='Gamma Srl', tax_code='GAMMA1234')
        active_supplier.wfm.transition(user1, 'proposed', user1)
        active_supplier.wfm.transition(manager1, 'proposed', manager1, message='Activating for demo data.')
        active_supplier.wfm.transition(manager1, 'active', manager1)
        self.stdout.write(self.style.SUCCESS('Created 1 sample supplier (active, owned by manager1).'))

        for title, budget in [('Buy office chairs', '450.00'), ('Renew software license', '1200.00')]:
            request = Request.objects.create(
                title=title, budget=Decimal(budget), supplier=active_supplier,
            )
            request.wfm.transition(user1, 'draft', user1)
        self.stdout.write(self.style.SUCCESS('Created 2 sample requests (draft, owned by user1).'))
