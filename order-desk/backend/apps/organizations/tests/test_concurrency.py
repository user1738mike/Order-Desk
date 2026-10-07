from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections
from django.test import TransactionTestCase, skipUnlessDBFeature

from apps.accounts.models import User
from apps.organizations.models import Membership
from apps.organizations.services import add_member, create_organization


@skipUnlessDBFeature("has_select_for_update")
class MembershipConcurrencyTests(TransactionTestCase):
    def test_simultaneous_duplicate_adds_create_one_membership(self) -> None:
        admin = User.objects.create_user(email="admin@example.test")
        target = User.objects.create_user(email="target@example.test")
        organization = create_organization(actor=admin, name="Concurrent Distributor")
        barrier = Barrier(2)

        def attempt_add() -> str:
            close_old_connections()
            try:
                actor = User.objects.get(pk=admin.pk)
                barrier.wait(timeout=10)
                add_member(
                    actor=actor,
                    organization_id=organization.pk,
                    user_id=target.pk,
                )
                return "created"
            except ValidationError:
                return "duplicate"
            finally:
                # Each worker owns its connection; do not leave one open for flush.
                connections["default"].close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(attempt_add) for _ in range(2)]
            results = [future.result(timeout=20) for future in futures]

        self.assertCountEqual(results, ["created", "duplicate"])
        self.assertEqual(
            Membership.objects.filter(organization=organization, user=target).count(), 1
        )
