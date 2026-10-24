"""Actual restricted connections; owner alias is for synthetic fixtures only."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4

from django.core.management.base import CommandError
from django.db import close_old_connections, connection, transaction

from apps.catalog.tests.runtime_rls import (
    OWNER_ALIAS,
    RuntimeCatalogRLSChecks,
    _forged_policy_context,
)
from apps.customers.models import CustomerAccount
from apps.organizations.models import Membership, MembershipRole
from apps.organizations.transactions import tenant_scope
from apps.product_units.models import (
    ControlledUnit,
    CustomerProductAlias,
    DraftLineUnitDecision,
    OrderLineUnitSnapshot,
    ProductUnitPolicy,
    UnitReferenceReceipt,
)
from apps.product_units.references import save_reference

TABLES = {
    "controlledunit": "unit_ref",
    "productunitpolicy": "unit_policy",
    "customerproductalias": "product_alias",
    "unitreferencereceipt": "unit_receipt",
    "draftlineunitdecision": "unit_decision",
    "orderlineunitsnapshot": "unit_snapshot",
}


def audit(cursor):
    for suffix, prefix in TABLES.items():
        table = "product_units_" + suffix
        cursor.execute(
            "SELECT pg_get_userbyid(relowner),relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass",
            [table],
        )
        if cursor.fetchone() != ("orderdesk_migrator", True, True):
            raise CommandError("Unit ownership/forced RLS mismatch.")
        for privilege in (
            "SELECT",
            "INSERT",
            "UPDATE",
            "DELETE",
            "TRUNCATE",
            "REFERENCES",
            "TRIGGER",
            "MAINTAIN",
        ):
            expected = (
                privilege == "SELECT"
                or (
                    suffix not in {"draftlineunitdecision", "orderlineunitsnapshot"}
                    and privilege == "INSERT"
                )
                or (
                    suffix
                    in {"controlledunit", "productunitpolicy", "customerproductalias"}
                    and privilege == "UPDATE"
                )
            )
            cursor.execute(
                "SELECT has_table_privilege(current_user,%s,%s)", [table, privilege]
            )
            if cursor.fetchone()[0] is not expected:
                raise CommandError("Unit table grant mismatch.")
        cursor.execute(
            "SELECT policyname,permissive,roles,cmd,qual,with_check FROM pg_policies WHERE schemaname='public' AND tablename=%s",
            [table],
        )
        policies = {row[0]: row[1:] for row in cursor.fetchall()}
        expected = {
            "_tenant_boundary": ("RESTRICTIVE", ["orderdesk_app"], "ALL"),
            "_member_read": ("PERMISSIVE", ["orderdesk_app"], "SELECT"),
            "_reviewer_insert": ("PERMISSIVE", ["orderdesk_app"], "INSERT"),
            "_reviewer_update": ("PERMISSIVE", ["orderdesk_app"], "UPDATE"),
            "_owner_maintenance": ("PERMISSIVE", ["orderdesk_migrator"], "ALL"),
        }
        if set(policies) != {prefix + name for name in expected}:
            raise CommandError("Unit policy set mismatch.")
        for name, header in expected.items():
            if policies[prefix + name][:3] != header:
                raise CommandError("Unit policy composition mismatch.")
        tenant = policies[prefix + "_tenant_boundary"]
        if tenant[3] != tenant[4] or any(
            value not in tenant[3]
            for value in (
                "orderdesk.organization_id",
                "orderdesk.user_id",
                "m.is_active",
                "o.is_active",
                "u.is_active",
            )
        ):
            raise CommandError("Unit tenant policy lacks active identity boundaries.")
        insert = policies[prefix + "_reviewer_insert"]
        update = policies[prefix + "_reviewer_update"]
        if (
            insert[3] is not None
            or not insert[4]
            or update[3] != update[4]
            or insert[4] != update[4]
        ):
            raise CommandError("Unit write policy mismatch.")
        if suffix != "draftlineunitdecision" and any(
            role in insert[4] for role in ("reviewer", "processor")
        ):
            raise CommandError("Reference write policy is not admin-only.")
        if policies[prefix + "_member_read"][3:] != ("true", None) or policies[
            prefix + "_owner_maintenance"
        ][3:] != ("true", "true"):
            raise CommandError("Unexpected unit maintenance/read policy.")
    cursor.execute(
        "SELECT count(*) FROM pg_constraint WHERE conname IN ('unit_policy_product_fk','unit_policy_requested_fk','unit_policy_selling_fk','unit_policy_destination_fk','product_alias_customer_fk','product_alias_product_fk','unit_receipt_unit_fk','unit_receipt_policy_fk','unit_receipt_alias_fk','unit_decision_line_fk','unit_decision_policy_fk','unit_decision_alias_fk','unit_decision_customer_fk','unit_snapshot_line_fk','unit_snapshot_decision_fk') AND contype='f' AND condeferrable AND NOT condeferred"
    )
    if cursor.fetchone()[0] != 15:
        raise CommandError("Unit composite references are incomplete.")


class RuntimeUnitChecks(RuntimeCatalogRLSChecks):
    def _cleanup_fixtures(self):
        connection.close()
        with transaction.atomic(using=OWNER_ALIAS):
            for model in (
                OrderLineUnitSnapshot,
                DraftLineUnitDecision,
                UnitReferenceReceipt,
                ProductUnitPolicy,
                CustomerProductAlias,
                ControlledUnit,
                CustomerAccount,
            ):
                model.objects.using(OWNER_ALIAS).filter(
                    organization_id__in=self.workspace_ids
                ).delete()
        super()._cleanup_fixtures()

    def unit(self, code="ea", org=None):
        return save_reference(
            actor=self.admin,
            organization_id=(org or self.a).pk,
            kind="unit",
            data=lambda: {"code": code, "display_name": "Synthetic unit"},
            operation_key=uuid4(),
        )

    def test_unit_actual_identity_unscoped_foreign_actor_and_immutable_receipt(self):
        a, b = self.unit(), self.unit(org=self.b)
        self.assertEqual(list(ControlledUnit.objects.all()), [])
        with tenant_scope(user=self.admin, workspace_id=self.a.pk):
            self.assertEqual(
                list(ControlledUnit.objects.values_list("id", flat=True)),
                [UUID(a["id"])],
            )
            self.assertEqual(ControlledUnit.objects.filter(pk=b["id"]).count(), 0)
        self._expect_error(
            "23514",
            self._write_scope(),
            lambda: ControlledUnit.objects.create(
                organization_id=self.a.pk,
                created_by_id=self.viewer.pk,
                updated_by_id=self.admin.pk,
                code="BAD",
                display_name="Denied",
            ),
        )
        self._expect_error(
            "42501",
            self._write_scope(),
            lambda: UnitReferenceReceipt.objects.update(response={}),
        )
        self._expect_error(
            "42501", self._write_scope(), lambda: ControlledUnit.objects.all().delete()
        )

    def test_unit_reference_role_and_revocation_not_bypassed_by_forged_context(self):
        self.unit()
        for role in (
            MembershipRole.REVIEWER,
            MembershipRole.PROCESSOR,
            MembershipRole.VIEWER,
        ):
            Membership.objects.using(OWNER_ALIAS).filter(
                pk=self.admin_membership.pk
            ).update(role=role)
            self._expect_error(
                "42501",
                self._write_scope(),
                lambda: ControlledUnit.objects.create(
                    organization_id=self.a.pk,
                    created_by_id=self.admin.pk,
                    updated_by_id=self.admin.pk,
                    code="DENIED",
                    display_name="Denied",
                ),
            )
        Membership.objects.using(OWNER_ALIAS).filter(
            pk=self.admin_membership.pk
        ).update(is_active=False)
        with _forged_policy_context(self.a.pk, self.admin.pk):
            self.assertEqual(ControlledUnit.objects.count(), 0)

    def test_unit_cross_tenant_policy_parent_is_denied_by_composite_fk(self):
        unit = self.unit()
        self._expect_error(
            "23503",
            self._write_scope(),
            lambda: ProductUnitPolicy.objects.create(
                organization_id=self.a.pk,
                created_by_id=self.admin.pk,
                updated_by_id=self.admin.pk,
                catalogue_item_id=self.item_b.pk,
                requested_token="ea",
                requested_unit_id=unit["id"],
                selling_unit_id=unit["id"],
                selling_numerator="1",
                selling_denominator="1",
                selling_scale=3,
                selling_max_integer_digits=9,
                provenance="Forged foreign parent",
            ),
        )

    def test_unit_same_key_independent_connections_commit_one_receipt(self):
        key, barrier = uuid4(), Barrier(2)
        identities = []

        def contender(_):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout='8s'")
                    cursor.execute("SET statement_timeout='12s'")
                    cursor.execute("SELECT current_user,session_user,pg_backend_pid()")
                    identities.append(cursor.fetchone())
                barrier.wait(timeout=10)
                return save_reference(
                    actor=self.admin,
                    organization_id=self.a.pk,
                    kind="unit",
                    data=lambda: {"code": "000EA", "display_name": "Synthetic each"},
                    operation_key=key,
                )
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(contender, range(2)))
        self.assertEqual({row["id"] for row in results}, {results[0]["id"]})
        self.assertCountEqual([row["replayed"] for row in results], [False, True])
        self.assertEqual(len({row[2] for row in identities}), 2)
        self.assertTrue(
            all(row[:2] == ("orderdesk_app", "orderdesk_app") for row in identities)
        )
        with tenant_scope(user=self.admin, workspace_id=self.a.pk):
            self.assertEqual(UnitReferenceReceipt.objects.count(), 1)
