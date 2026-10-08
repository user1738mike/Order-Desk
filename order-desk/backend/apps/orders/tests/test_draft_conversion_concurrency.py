"""Independent PostgreSQL connections observe both organization-lock serial orders."""

from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Event
from time import monotonic
from uuid import uuid4

from django.core.exceptions import PermissionDenied
from django.db import close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase

from apps.accounts.models import User
from apps.catalog.models import CatalogItem
from apps.catalog.services import update_catalog_item
from apps.orders import services
from apps.orders.models import (
    DraftOrder,
    DraftOrderLine,
    PurchaseOrder,
    PurchaseOrderLine,
)
from apps.organizations.models import Membership, MembershipRole, Organization
from apps.organizations.services import create_organization


class DraftConversionConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="conversion-race@example.test")

    @staticmethod
    def pid():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            return cursor.fetchone()[0]

    def fixture(self, *, unmatched=False):
        org = create_organization(actor=self.user, name="Synthetic conversion race")
        draft = DraftOrder.objects.create(
            organization=org, initiating_user=self.user, customer_name="Buyer"
        )
        item = CatalogItem.objects.create(organization=org, sku=uuid4().hex)
        line = DraftOrderLine.objects.create(
            organization=org,
            order=draft,
            position=1,
            quantity=2,
            requested_sku="Original",
            catalogue_item=None if unmatched else item,
            catalogue_sku_snapshot="" if unmatched else item.sku,
        )
        return org, draft, line, item

    def ordered_race(self, first, second, *, conversion_first):
        held, waiter = Queue(), Queue()
        release = Event()

        def hold(value):
            held.put(self.pid())
            if not release.wait(15):
                raise RuntimeError("Race release timed out")
            return value.pk if hasattr(value, "pk") else value

        def worker(action, leading):
            close_old_connections()
            try:
                observed = False

                def inspect(execute, statement, params, many, context):
                    nonlocal observed
                    if (
                        leading
                        and conversion_first
                        and not observed
                        and "COUNT(" in statement
                        and "orders_draftorder" in statement
                    ):
                        observed = True
                        hold(None)
                    return execute(statement, params, many, context)

                if not leading:
                    waiter.put(self.pid())
                try:
                    with connection.execute_wrapper(inspect):
                        value = action(
                            hold
                            if leading and not conversion_first
                            else lambda row: row.pk
                        )
                    outcome = ("ok", value)
                except (
                    services.DraftAlreadyConverted,
                    services.DraftNotReady,
                    PermissionDenied,
                ) as error:
                    outcome = (type(error).__name__, None)
                self.assertFalse(connection.in_atomic_block)
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT NULLIF(current_setting("
                        "'orderdesk.organization_id', true), '')"
                    )
                    self.assertEqual(cursor.fetchone(), (None,))
                return outcome
            finally:
                connections["default"].close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first_future = pool.submit(worker, first, True)
            try:
                blocker = held.get(timeout=10)
                second_future = pool.submit(worker, second, False)
                waiting = waiter.get(timeout=10)
                self.assertNotEqual(blocker, waiting)
                deadline = monotonic() + 5
                pause = Event()
                while monotonic() < deadline:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_blocking_pids(%s)", [waiting])
                        if blocker in cursor.fetchone()[0]:
                            break
                    pause.wait(0.02)
                else:
                    self.fail("Expected organization lock wait was not observed")
            finally:
                release.set()
            return first_future.result(timeout=20), second_future.result(timeout=20)

    def test_conversion_against_every_relevant_writer_in_both_serial_orders(self):
        for variant in (
            "header",
            "line_edit",
            "line_insert",
            "detach",
            "attach",
            "deactivate",
            "demote",
            "revoke",
        ):
            for conversion_first in (True, False):
                with self.subTest(variant=variant, conversion_first=conversion_first):
                    org, draft, line, item = self.fixture(unmatched=variant == "attach")
                    base = dict(
                        actor=self.user, organization_id=org.pk, order_id=draft.pk
                    )

                    def convert(materialize, base=base):
                        return services.convert_draft_to_purchase_order(
                            **base, data={}, materialize=materialize
                        )

                    def mutate(
                        materialize,
                        variant=variant,
                        base=base,
                        line=line,
                        item=item,
                        org=org,
                    ):
                        if variant == "header":
                            return services.update_draft_customer_fields(
                                **base,
                                data={"customer_name": "New buyer"},
                                materialize=materialize,
                            )
                        if variant == "line_edit":
                            return services.update_draft_order_line(
                                **base,
                                line_id=line.pk,
                                data={"quantity": 3},
                                materialize=materialize,
                            )
                        if variant == "line_insert":
                            return services.create_draft_order_line(
                                **base,
                                data={"position": 2, "requested_sku": "New"},
                                materialize=materialize,
                            )
                        if variant == "detach":
                            return services.detach_catalogue_item_from_draft_order_line(
                                **base,
                                line_id=line.pk,
                                data={},
                                materialize=materialize,
                            )
                        if variant == "attach":
                            return services.attach_catalogue_item_to_draft_order_line(
                                **base,
                                line_id=line.pk,
                                catalogue_item_id=item.pk,
                                materialize=materialize,
                            )
                        if variant == "deactivate":
                            return update_catalog_item(
                                actor=self.user,
                                organization_id=org.pk,
                                item_id=item.pk,
                                data={"is_active": False},
                                materialize=materialize,
                            )
                        with transaction.atomic():
                            Organization.objects.select_for_update().get(pk=org.pk)
                            changes = (
                                {"role": MembershipRole.REVIEWER}
                                if variant == "demote"
                                else {"is_active": False}
                            )
                            Membership.objects.filter(
                                user=self.user, organization=org
                            ).update(**changes)
                            return materialize(org)

                    first, second = self.ordered_race(
                        convert if conversion_first else mutate,
                        mutate if conversion_first else convert,
                        conversion_first=conversion_first,
                    )
                    converted = first if conversion_first else second
                    expected = (
                        (variant != "attach")
                        if conversion_first
                        else variant in {"header", "line_edit", "attach"}
                    )
                    self.assertEqual(converted[0] == "ok", expected, (first, second))
                    self.assertEqual(
                        PurchaseOrder.objects.filter(source_draft=draft).count(),
                        int(expected),
                    )
                    draft.refresh_from_db()
                    self.assertEqual(draft.status, "converted" if expected else "draft")
                    if expected:
                        order = PurchaseOrder.objects.get(source_draft=draft)
                        copied = PurchaseOrderLine.objects.get(order=order)
                        self.assertEqual(copied.sku, item.sku)
                        self.assertEqual(
                            copied.quantity,
                            3 if variant == "line_edit" and not conversion_first else 2,
                        )
                        self.assertEqual(
                            order.customer_name,
                            "New buyer"
                            if variant == "header" and not conversion_first
                            else "Buyer",
                        )
                    if conversion_first and variant in {
                        "header",
                        "line_edit",
                        "line_insert",
                        "detach",
                    }:
                        self.assertEqual(second[0], "DraftAlreadyConverted")
