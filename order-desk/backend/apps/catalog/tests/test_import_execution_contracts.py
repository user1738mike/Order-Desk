"""Pure replay contracts and actual PostgreSQL execution/rollback behavior."""

import json
import secrets
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

from django.core.exceptions import PermissionDenied
from django.db import (
    DatabaseError,
    IntegrityError,
    connection,
    connections,
    transaction,
)
from django.test import SimpleTestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.catalog import import_execution
from apps.catalog.import_execution import (
    CATALOG_IMPORT_DENIED,
    CATALOG_IMPORT_KEY_REUSED,
    CATALOG_IMPORT_ROWS_INVALID,
    ImportKeyConflict,
    ImportRowsInvalid,
    ImportSKUConflict,
    execute_catalogue_import,
    import_fingerprint,
    parse_import_key,
)
from apps.catalog.imports import (
    MAX_FILE_BYTES,
    ImportStructureError,
    ImportUploadTooLarge,
)
from apps.catalog.models import CONTRACT_IDENTIFIER, CatalogImportReceipt, CatalogItem
from apps.catalog.serializers import CatalogItemSerializer
from apps.catalog.services import CATALOG_SKU_CONFLICT
from apps.catalog.tests.test_create_api import PUBLIC_FIELDS
from apps.catalog.tests.test_import_contracts import csv_bytes
from apps.catalog.tests.test_update_api import CatalogUpdateTestCase
from apps.organizations.access import WORKSPACE_ACCESS_DENIED
from apps.organizations.models import Membership, MembershipRole, Organization
from apps.organizations.transactions import TenantScopeError

SUCCESS_FIELDS = {
    "import_id",
    "organization_id",
    "mode",
    "created_count",
    "items",
    "items_truncated",
}


class ImportExecutionPureContracts(SimpleTestCase):
    def test_uuid_header_formats_normalize_to_the_same_key(self):
        key = uuid4()
        for value in (key, str(key), key.hex.upper(), "{" + str(key) + "}", key.urn):
            with self.subTest(value=value):
                self.assertEqual(parse_import_key(value), key)

    def test_bad_or_missing_keys_have_a_safe_field_error(self):
        for value in (None, "", "not-a-uuid", " " + str(uuid4()), 1, False, [], {}):
            with self.subTest(value=value), self.assertRaises(ValidationError) as error:
                parse_import_key(value)
            self.assertEqual(error.exception.status_code, 400)
            self.assertEqual(set(error.exception.detail), {"idempotency_key"})
            self.assertEqual(
                str(error.exception.detail["idempotency_key"][0]),
                "Provide a valid Idempotency-Key UUID header.",
            )

    def test_fingerprint_has_a_fixed_operation_and_contract_vector(self):
        self.assertEqual(
            import_fingerprint(b"sku,description,is_active\nA,,\n"),
            "148b9aeaa4b4ac375262031f9c2139153834e9d9879ff13dbcdf84ec8e6ff7a8",
        )

    def test_raw_bom_line_endings_and_record_order_change_the_fingerprint(self):
        raw = csv_bytes([["A", "", ""], ["B", "", ""]], newline="\n")
        variants = (
            raw,
            b"\xef\xbb\xbf" + raw,
            raw.replace(b"\n", b"\r\n"),
            csv_bytes([["B", "", ""], ["A", "", ""]], newline="\n"),
        )
        self.assertEqual(len({import_fingerprint(value) for value in variants}), 4)
        self.assertEqual(import_fingerprint(raw), import_fingerprint(bytes(raw)))

    def test_contract_version_is_included_in_the_fingerprint(self):
        raw = csv_bytes([["A", "", ""]])
        original = import_fingerprint(raw)
        with patch.object(import_execution, "CONTRACT_IDENTIFIER", "future-contract"):
            self.assertNotEqual(import_fingerprint(raw), original)

    def test_file_bound_is_enforced_before_hashing(self):
        self.assertEqual(len(import_fingerprint(b"x" * MAX_FILE_BYTES)), 64)
        with (
            patch.object(import_execution.hashlib, "sha256") as digest,
            self.assertRaises(ImportUploadTooLarge) as error,
        ):
            import_fingerprint(b"x" * (MAX_FILE_BYTES + 1))
        digest.assert_not_called()
        self.assertEqual(error.exception.status_code, 413)

    def test_fingerprint_rejects_nonbyte_input(self):
        for raw in ("text", bytearray(b"text"), None):
            with self.subTest(raw=raw), self.assertRaises(TypeError):
                import_fingerprint(raw)

    def test_canonical_payload_preserves_types_unicode_and_list_order(self):
        payload = {"z": [{"z": False, "a": 2}], "a": "\u00e9\n"}
        canonical = import_execution._canonical_payload(payload)
        self.assertEqual(list(canonical), ["a", "z"])
        self.assertEqual(list(canonical["z"][0]), ["a", "z"])
        self.assertIs(canonical["z"][0]["z"], False)
        self.assertIsInstance(canonical["z"][0]["a"], int)
        self.assertEqual(canonical["a"], "\u00e9\n")
        reordered = {"a": payload["a"], "z": [{"a": 2, "z": False}]}
        self.assertEqual(
            json.dumps(canonical),
            json.dumps(import_execution._canonical_payload(reordered)),
        )

    def test_completed_receipt_replays_only_the_stored_response(self):
        raw = csv_bytes([["A", "", ""]])
        receipt = CatalogImportReceipt(
            request_fingerprint=import_fingerprint(raw),
            state=CatalogImportReceipt.State.COMPLETED,
            response_payload={"z": {"z": 3, "a": True}, "a": "stored"},
            completed_at=timezone.now(),
        )
        result = import_execution._receipt_result(receipt, import_fingerprint(raw))
        self.assertTrue(result.replayed)
        self.assertEqual(result.payload, receipt.response_payload)
        self.assertEqual(list(result.payload), ["a", "z"])

    def test_receipt_request_or_contract_mismatch_is_a_conflict(self):
        receipt = CatalogImportReceipt(
            request_fingerprint="a" * 64,
            state=CatalogImportReceipt.State.COMPLETED,
            response_payload={},
            completed_at=timezone.now(),
        )
        for field, value in (
            ("request_fingerprint", "b" * 64),
            ("mode", "update"),
            ("contract_identifier", "future-contract"),
        ):
            before = getattr(receipt, field)
            setattr(receipt, field, value)
            with (
                self.subTest(field=field),
                self.assertRaises(ImportKeyConflict) as error,
            ):
                import_execution._receipt_result(receipt, "a" * 64)
            self.assertEqual(error.exception.status_code, 409)
            self.assertEqual(str(error.exception.detail), CATALOG_IMPORT_KEY_REUSED)
            setattr(receipt, field, before)

    def test_abnormal_processing_or_malformed_completed_receipts_are_not_resumed(self):
        for state, payload, completed in (
            (CatalogImportReceipt.State.PROCESSING, None, None),
            (CatalogImportReceipt.State.COMPLETED, {}, None),
            (CatalogImportReceipt.State.COMPLETED, [], timezone.now()),
        ):
            receipt = CatalogImportReceipt(
                request_fingerprint="a" * 64,
                state=state,
                response_payload=payload,
                completed_at=completed,
            )
            with (
                self.subTest(state=state, payload=payload),
                self.assertRaises(RuntimeError),
            ):
                import_execution._receipt_result(receipt, "a" * 64)

    def test_error_reports_keep_boolean_and_integer_json_values(self):
        report = {"can_import": False, "summary": {"rows_total": 7}}
        for exception, detail, status in (
            (ImportRowsInvalid, CATALOG_IMPORT_ROWS_INVALID, 400),
            (ImportSKUConflict, CATALOG_SKU_CONFLICT, 409),
        ):
            error = exception(report)
            self.assertEqual(error.status_code, status)
            self.assertEqual(error.detail["detail"], detail)
            self.assertIs(error.detail["report"]["can_import"], False)
            self.assertIsInstance(error.detail["report"]["summary"]["rows_total"], int)


class ImportExecutionServiceContracts(CatalogUpdateTestCase):
    """Owner-backed native constraints; direct runtime-role proof is separate."""

    def execute(self, raw=None, *, key=None, actor=None, workspace=None):
        return execute_catalogue_import(
            actor=actor or self.admin,
            organization_id=(workspace or self.a).pk,
            data=raw if raw is not None else csv_bytes([["NEW", "", ""]]),
            idempotency_key=key or uuid4(),
        )

    def assert_rolled_back(self, *skus):
        self.assertFalse(CatalogImportReceipt.objects.exists())
        self.assertFalse(CatalogItem.objects.filter(sku__in=skus).exists())
        self.assert_clean()

    def inspect_scope(self):
        self.assertTrue(connection.in_atomic_block)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_setting('transaction_read_only'), "
                "current_setting('orderdesk.organization_id'), "
                "current_setting('orderdesk.user_id')"
            )
            self.assertEqual(
                cursor.fetchone(), ("off", str(self.a.pk), str(self.admin.pk))
            )

    def test_first_execution_saves_sorted_but_returns_original_csv_order(self):
        raw = csv_bytes([["Z-NEW", "  Last\n ", "false"], ["A-NEW", "First", ""]])
        key = uuid4()
        saved = []
        original_save = CatalogItem.save

        def save(item, *args, **kwargs):
            saved.append(item.sku)
            return original_save(item, *args, **kwargs)

        before = self.state()
        with patch.object(CatalogItem, "save", save):
            result = self.execute(raw, key=key)
        self.assertFalse(result.replayed)
        self.assertEqual(saved, ["A-NEW", "Z-NEW"])
        self.assertEqual(set(result.payload), SUCCESS_FIELDS)
        self.assertEqual(result.payload["organization_id"], str(self.a.pk))
        self.assertEqual(result.payload["mode"], "create_only")
        self.assertEqual(result.payload["created_count"], 2)
        self.assertFalse(result.payload["items_truncated"])
        self.assertEqual([row["sku"] for row in result.payload["items"]], saved[::-1])
        self.assertEqual(result.payload["items"][0]["description"], "  Last\n ")
        self.assertIs(result.payload["items"][0]["is_active"], False)
        for row in result.payload["items"]:
            self.assertEqual(set(row), PUBLIC_FIELDS)
            self.assertEqual(row["organization_id"], str(self.a.pk))
        receipt = CatalogImportReceipt.objects.get(pk=result.payload["import_id"])
        self.assertEqual(receipt.idempotency_key, key)
        self.assertEqual(receipt.initiating_user_id, self.admin.pk)
        self.assertEqual(receipt.request_fingerprint, import_fingerprint(raw))
        self.assertEqual(receipt.contract_identifier, CONTRACT_IDENTIFIER)
        self.assertEqual(receipt.state, CatalogImportReceipt.State.COMPLETED)
        self.assertGreaterEqual(receipt.completed_at, receipt.created_at)
        self.assertEqual(receipt.response_payload, result.payload)
        self.assertEqual(self.state(), before)
        self.assert_clean()

    def test_callback_queries_and_scalar_materialization_are_inside_owned_scope(self):
        statements = []
        original_serialize = CatalogItemSerializer.to_representation

        def observe(execute, sql, params, many, context):
            if "catalog_catalog" in sql:
                self.inspect_scope()
            statements.append(sql)
            return execute(sql, params, many, context)

        def data():
            self.inspect_scope()
            self.assertTrue(
                any(
                    "organizations_organization" in sql and "FOR UPDATE" in sql
                    for sql in statements
                )
            )
            return csv_bytes([["SCOPED", "", ""]])

        def serialize(serializer, item):
            self.inspect_scope()
            with self.assertNumQueries(0):
                return original_serialize(serializer, item)

        with (
            connection.execute_wrapper(observe),
            patch.object(CatalogItemSerializer, "to_representation", serialize),
        ):
            result = self.execute(data)
        self.assert_clean()
        with patch.object(connection, "cursor", side_effect=AssertionError("Late SQL")):
            self.assertEqual(json.loads(json.dumps(result.payload)), result.payload)
        completions = [
            sql
            for sql in statements
            if sql.startswith("UPDATE") and '"catalog_catalogimportreceipt"' in sql
        ]
        self.assertEqual(len(completions), 1)
        assigned = completions[0].split(" SET ", 1)[1].split(" WHERE ", 1)[0]
        self.assertEqual(assigned.count(" = "), 3)
        for column in ("state", "response_payload", "completed_at"):
            self.assertIn('"' + column + '"', assigned)

    def test_replay_avoids_parser_and_catalog_queries_and_preserves_old_response(self):
        raw = csv_bytes([["REPLAY", "Original imported", ""]])
        key = uuid4()
        first = self.execute(raw, key=key)
        CatalogItem.objects.filter(sku="REPLAY").update(
            description="Later edited", is_active=False
        )
        statements = []

        def observe(execute, sql, params, many, context):
            statements.append(sql)
            return execute(sql, params, many, context)

        with (
            connection.execute_wrapper(observe),
            patch.object(
                import_execution,
                "parse_catalogue_csv",
                side_effect=AssertionError("Replay parsed CSV"),
            ),
        ):
            replay = self.execute(raw, key=key)
        self.assertTrue(replay.replayed)
        self.assertEqual(json.dumps(first.payload), json.dumps(replay.payload))
        self.assertFalse(any('"catalog_catalogitem"' in sql for sql in statements))
        self.assertEqual(CatalogImportReceipt.objects.count(), 1)
        self.assert_clean()

    def test_another_current_admin_replays_without_changing_the_initiator(self):
        raw = csv_bytes([["PEER-REPLAY", "", ""]])
        key = uuid4()
        first = self.execute(raw, key=key)
        replay = self.execute(raw, key=key, actor=self.peer_admin)
        self.assertTrue(replay.replayed)
        self.assertEqual(json.dumps(first.payload), json.dumps(replay.payload))
        receipt = CatalogImportReceipt.objects.get(pk=first.payload["import_id"])
        self.assertEqual(receipt.initiating_user_id, self.admin.pk)
        self.assert_clean()

    def test_changed_raw_bytes_conflict_before_csv_parser_or_sku_lookup(self):
        raw = csv_bytes([["REUSED", "", ""]])
        key = uuid4()
        first = self.execute(raw, key=key)
        with (
            patch.object(
                import_execution,
                "parse_catalogue_csv",
                side_effect=AssertionError("Conflict parsed CSV"),
            ),
            self.assertRaises(ImportKeyConflict) as error,
        ):
            self.execute(raw + b"\n", key=key)
        self.assertEqual(str(error.exception.detail), CATALOG_IMPORT_KEY_REUSED)
        receipt = CatalogImportReceipt.objects.get(pk=first.payload["import_id"])
        self.assertEqual(receipt.response_payload, first.payload)
        self.assertEqual(CatalogItem.objects.filter(sku="REUSED").count(), 1)
        self.assert_clean()

    def test_same_key_and_sku_are_independent_in_different_workspaces(self):
        key = uuid4()
        raw = csv_bytes([["TENANT-LOCAL", "", ""]])
        first = self.execute(raw, key=key)
        second = self.execute(raw, key=key, workspace=self.b)
        self.assertFalse(second.replayed)
        self.assertNotEqual(first.payload["import_id"], second.payload["import_id"])
        self.assertEqual(second.payload["organization_id"], str(self.b.pk))
        self.assertEqual(CatalogItem.objects.filter(sku="TENANT-LOCAL").count(), 2)
        self.assertEqual(
            CatalogImportReceipt.objects.filter(idempotency_key=key).count(), 2
        )
        self.assert_clean()

    def test_invalid_rows_return_full_bounded_report_and_leave_key_reusable(self):
        key = uuid4()
        rows = [["BAD-" + str(index), "", "TRUE"] for index in range(110)]
        with self.assertRaises(ImportRowsInvalid) as error:
            self.execute(csv_bytes(rows), key=key)
        report = error.exception.detail["report"]
        self.assertEqual(
            report["summary"], {"rows_total": 110, "rows_ready": 0, "rows_invalid": 110}
        )
        self.assertEqual(len(report["errors"]), 100)
        self.assertIs(report["errors_truncated"], True)
        self.assertIs(report["can_import"], False)
        self.assert_rolled_back(*(row[0] for row in rows))
        self.assertFalse(self.execute(key=key).replayed)

    def test_structural_failure_rolls_back_reservation_and_key_is_reusable(self):
        key = uuid4()
        with self.assertRaises(ImportStructureError):
            self.execute(b"wrong,headers\nA,B\n", key=key)
        self.assert_rolled_back("NEW")
        self.assertFalse(self.execute(key=key).replayed)

    def test_normalized_duplicates_invalidate_every_occurrence_without_inserts(self):
        with self.assertRaises(ImportRowsInvalid) as error:
            self.execute(csv_bytes([[" DUP ", "", ""], ["DUP", "", ""]]))
        report = error.exception.detail["report"]
        self.assertEqual(report["summary"]["rows_invalid"], 2)
        self.assertEqual([row["row_number"] for row in report["errors"]], [2, 3])
        self.assert_rolled_back("DUP")

    def test_active_and_inactive_existing_skus_are_conflicts_without_changes(self):
        before = self.state()
        for active in (True, False):
            CatalogItem.objects.filter(pk=self.item.pk).update(is_active=active)
            raw = csv_bytes([["FRESH", "", ""], [self.item.sku, "replacement", ""]])
            with (
                self.subTest(active=active),
                self.assertRaises(ImportSKUConflict) as error,
            ):
                self.execute(raw)
            self.assertEqual(error.exception.detail["detail"], CATALOG_SKU_CONFLICT)
            self.assertEqual(
                error.exception.detail["report"]["summary"],
                {"rows_total": 2, "rows_ready": 1, "rows_invalid": 1},
            )
            self.assert_rolled_back("FRESH")
            state = self.state()
            self.assertEqual(state, {**before, "is_active": active})

    def test_sku_existing_only_in_another_workspace_is_allowed(self):
        CatalogItem.objects.create(organization=self.b, sku="FOREIGN-ONLY")
        result = self.execute(csv_bytes([["FOREIGN-ONLY", "", ""]]))
        self.assertEqual(result.payload["created_count"], 1)
        self.assertEqual(CatalogItem.objects.filter(sku="FOREIGN-ONLY").count(), 2)
        self.assert_clean()

    def test_nonadmins_are_denied_before_key_callback_and_receipt_lookup(self):
        for actor in (self.viewer, self.reviewer):
            callback = Mock(side_effect=AssertionError("Unauthorized file parsed"))
            with (
                self.subTest(actor=actor.pk),
                self.assertRaises(PermissionDenied) as error,
            ):
                execute_catalogue_import(
                    actor=actor,
                    organization_id=self.a.pk,
                    data=callback,
                    idempotency_key="invalid",
                )
            self.assertEqual(str(error.exception), CATALOG_IMPORT_DENIED)
            callback.assert_not_called()
            self.assert_rolled_back("NEW")

    def test_demoted_admin_and_inactive_memberships_are_freshly_denied(self):
        Membership.objects.filter(pk=self.admin_membership.pk).update(
            role=MembershipRole.VIEWER
        )
        callback = Mock(side_effect=AssertionError("Stale admin file parsed"))
        with self.assertRaises(PermissionDenied) as error:
            self.execute(callback)
        self.assertEqual(str(error.exception), CATALOG_IMPORT_DENIED)
        callback.assert_not_called()
        Membership.objects.filter(pk=self.admin_membership.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied) as error:
            self.execute(callback)
        self.assertEqual(str(error.exception), WORKSPACE_ACCESS_DENIED)
        callback.assert_not_called()
        self.assert_rolled_back("NEW")

    def test_inactive_user_workspace_and_operator_do_not_reach_file_callback(self):
        callback = Mock(side_effect=AssertionError("Unauthorized file parsed"))
        with self.assertRaises(PermissionDenied):
            self.execute(callback, actor=self.outsider)
        self.admin.is_active = False
        self.admin.save(update_fields=["is_active"])
        with self.assertRaises(PermissionDenied):
            self.execute(callback)
        self.admin.is_active = True
        self.admin.save(update_fields=["is_active"])
        Organization.objects.filter(pk=self.a.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            self.execute(callback)
        callback.assert_not_called()
        self.assert_rolled_back("NEW")

    def test_bad_key_is_rejected_before_file_callback_and_receipt_reservation(self):
        for key in (None, "invalid"):
            callback = Mock(side_effect=AssertionError("Bad key parsed file"))
            with self.subTest(key=key), self.assertRaises(ValidationError):
                execute_catalogue_import(
                    actor=self.admin,
                    organization_id=self.a.pk,
                    data=callback,
                    idempotency_key=key,
                )
            callback.assert_not_called()
        self.assert_rolled_back("NEW")

    def test_actual_oversized_bytes_are_rejected_without_a_receipt(self):
        with self.assertRaises(ImportUploadTooLarge):
            self.execute(b"x" * (MAX_FILE_BYTES + 1))
        self.assert_rolled_back("NEW")

    def test_caller_transaction_is_rejected_before_callback_without_disturbing_it(self):
        callback = Mock(side_effect=AssertionError("Nested execution read file"))
        with transaction.atomic():
            with self.assertRaises(TenantScopeError):
                self.execute(callback)
            self.assertTrue(connection.in_atomic_block)
            self.assertEqual(CatalogItem.objects.count(), 2)
        callback.assert_not_called()
        self.assert_rolled_back("NEW")

    def test_preview_is_bounded_after_all_records_are_committed(self):
        result = self.execute(
            csv_bytes([[f"ROW-{index:03d}", "", ""] for index in range(26)])
        )
        self.assertEqual(result.payload["created_count"], 26)
        self.assertEqual(len(result.payload["items"]), 25)
        self.assertIs(result.payload["items_truncated"], True)
        self.assertEqual(result.payload["items"][-1]["sku"], "ROW-024")
        self.assertEqual(CatalogItem.objects.filter(sku__startswith="ROW-").count(), 26)
        self.assert_clean()

    def test_unexpected_failure_after_second_save_rolls_back_every_write(self):
        key = uuid4()
        original_save = CatalogItem.save

        def save(item, *args, **kwargs):
            result = original_save(item, *args, **kwargs)
            if item.sku == "FAIL-B":
                raise ValueError("Synthetic failure after an actual second INSERT")
            return result

        with patch.object(CatalogItem, "save", save), self.assertRaises(ValueError):
            self.execute(csv_bytes([["FAIL-A", "", ""], ["FAIL-B", "", ""]]), key=key)
        self.assert_rolled_back("FAIL-A", "FAIL-B")
        self.assertFalse(self.execute(key=key).replayed)

    def test_serialization_failure_rolls_back_items_and_receipt(self):
        with (
            patch.object(
                CatalogItemSerializer,
                "to_representation",
                side_effect=ValueError("Synthetic serialization failure"),
            ),
            self.assertRaises(ValueError),
        ):
            self.execute()
        self.assert_rolled_back("NEW")

    def test_native_division_by_zero_at_completion_rolls_back_previous_insert(self):
        observed = False

        def fail(execute, sql, params, many, context):
            nonlocal observed
            if (
                not observed
                and sql.startswith("UPDATE")
                and "catalog_catalogimportreceipt" in sql
            ):
                observed = True
                self.assertTrue(CatalogItem.objects.filter(sku="NEW").exists())
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1 / 0")
            return execute(sql, params, many, context)

        with (
            connection.execute_wrapper(fail),
            self.assertRaises(DatabaseError) as error,
        ):
            self.execute()
        self.assertTrue(observed)
        self.assertEqual(error.exception.__cause__.sqlstate, "22012")
        self.assert_rolled_back("NEW")

    def test_native_sku_unique_race_is_a_safe_conflict_after_full_rollback(self):
        original_save = CatalogItem.save

        def save(item, *args, **kwargs):
            result = original_save(item, *args, **kwargs)
            if item.sku == "RACE-B":
                now = timezone.now()
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO public.catalog_catalogitem "
                        "(id, organization_id, sku, description, is_active, "
                        "created_at, updated_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        [
                            uuid4(),
                            self.a.pk,
                            item.sku,
                            "synthetic collision",
                            True,
                            now,
                            now,
                        ],
                    )
            return result

        with (
            patch.object(CatalogItem, "save", save),
            self.assertRaises(ImportSKUConflict) as error,
        ):
            self.execute(csv_bytes([["RACE-A", "", ""], ["RACE-B", "", ""]]))
        self.assertEqual(error.exception.__cause__.__cause__.sqlstate, "23505")
        self.assertEqual(error.exception.detail["report"]["summary"]["rows_invalid"], 1)
        self.assertEqual(error.exception.detail["report"]["errors"][0]["row_number"], 3)
        self.assert_rolled_back("RACE-A", "RACE-B")

    def test_unrelated_native_unique_error_is_not_mapped_to_a_sku_conflict(self):
        original_save = CatalogItem.save

        def save(item, *args, **kwargs):
            item.pk = self.item.pk
            return original_save(item, *args, **kwargs)

        before = self.state()
        with (
            patch.object(CatalogItem, "save", save),
            self.assertRaises(IntegrityError) as error,
        ):
            self.execute()
        self.assertEqual(error.exception.__cause__.sqlstate, "23505")
        self.assertNotEqual(
            error.exception.__cause__.diag.constraint_name, "catalog_org_sku_unique"
        )
        self.assert_rolled_back("NEW")
        self.assertEqual(self.state(), before)

    def test_native_index_limit_is_a_field_error_after_previous_rows_roll_back(self):
        sku = "Z" + secrets.token_urlsafe(3750)
        with self.assertRaises(ValidationError) as error:
            self.execute(csv_bytes([["A-SHORT", "", ""], [sku, "", ""]]))
        self.assertEqual(
            str(error.exception.detail["sku"][0]),
            "This stock code is too large for the catalogue index.",
        )
        self.assertEqual(error.exception.__cause__.__cause__.sqlstate, "54000")
        self.assert_rolled_back("A-SHORT", sku)

    def test_real_receipt_unique_collision_rolls_back_savepoint_then_replays_winner(
        self,
    ):
        raw = csv_bytes([["SAVEPOINT", "", ""]])
        first = self.execute(raw)
        receipt_id = UUID(first.payload["import_id"])
        target_key = uuid4()
        alias = "import_execution_collision_owner"
        owner = connection.copy(alias=alias)
        connections[alias] = owner
        moved = False

        def collide(execute, sql, params, many, context):
            nonlocal moved
            result = execute(sql, params, many, context)
            if (
                not moved
                and sql.startswith("SELECT")
                and '"catalog_catalogimportreceipt"' in sql
                and str(target_key) in {str(value) for value in params or ()}
            ):
                moved = True
                # A maintenance owner can move the synthetic completed key.
                # This changes no FK, so it avoids waiting on the org row lock.
                self.assertEqual(
                    CatalogImportReceipt.objects.using(alias)
                    .filter(pk=receipt_id)
                    .update(idempotency_key=target_key),
                    1,
                )
            return result

        try:
            with (
                connection.execute_wrapper(collide),
                patch.object(
                    import_execution,
                    "parse_catalogue_csv",
                    side_effect=AssertionError("Winner replay parsed CSV"),
                ),
            ):
                replay = self.execute(raw, key=target_key)
        finally:
            owner.close()
            del connections[alias]
        self.assertTrue(moved)
        self.assertTrue(replay.replayed)
        self.assertEqual(json.dumps(replay.payload), json.dumps(first.payload))
        self.assertEqual(CatalogImportReceipt.objects.count(), 1)
        self.assertEqual(CatalogItem.objects.filter(sku="SAVEPOINT").count(), 1)
        self.assert_clean()
