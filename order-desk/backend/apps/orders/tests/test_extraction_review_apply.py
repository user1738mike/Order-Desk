"""Explicit CSV decisions, atomic application receipts and PostgreSQL races."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal
from queue import Queue
from threading import Barrier, Event
from time import monotonic
from unittest.mock import patch
from uuid import uuid4

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.models import CatalogItem
from apps.orders.extraction_services import process_extraction
from apps.orders.models import (
    DocumentExtractionJob,
    DraftOrder,
    DraftOrderLine,
    OrderDocument,
    PurchaseOrder,
)
from apps.orders.revisions import draft_revision
from apps.orders.tests import test_private_document_intake as fixtures
from apps.organizations.context import resolve_workspace_context
from apps.organizations.models import Membership, MembershipRole, Organization
from apps.organizations.services import create_organization

CSV = (
    b"sku,quantity,description,unit\r\n0001.Mixed-Case,1.234,Source description,ea\r\n"
)


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ExtractionReviewApplyTests(TransactionTestCase):
    setUp = fixtures.PrivateDocumentIntakeTests.setUp
    upload = fixtures.PrivateDocumentIntakeTests.upload

    def ready(self, raw=CSV):
        response = self.upload(raw, "source.csv")
        self.assertEqual(response.status_code, 201, response.content)
        self.document = response.json()
        self.extraction = self.document["extraction_url"]
        queued = self.client.post(
            self.extraction, {}, format="json", HTTP_X_CSRFTOKEN=self.csrf
        )
        self.assertEqual(queued.status_code, 202, queued.content)
        self.job = DocumentExtractionJob.objects.get(pk=queued.json()["id"])
        self.assertEqual(
            process_extraction(
                actor=self.user,
                organization_id=self.organization.pk,
                job_id=self.job.pk,
            ),
            "succeeded",
        )
        self.draft = DraftOrder.objects.create(
            organization=self.organization,
            initiating_user=self.user,
            customer_name="Synthetic buyer",
            customer_reference="Manual reference",
            original_intake_text="Manual intake remains intact",
        )
        self.detail = (
            f"/api/v1/workspaces/{self.organization.pk}/draft-orders/{self.draft.pk}/"
        )
        self.apply_url = self.extraction + "apply/"
        self.review_url = self.extraction + f"review/?draft_id={self.draft.pk}"
        review = self.client.get(self.review_url)
        self.assertEqual(review.status_code, 200, review.content)
        self.review = review.json()

    def application_count(self):
        return apps.get_model("orders", "ExtractionApplication").objects.count()

    def payload(self, *, row=0, fields=None, **mapping):
        selected = {
            "candidate_id": self.review["results"][row]["candidate_id"],
            "action": "create",
            "position": row + 1,
            "fields": ["sku", "quantity", "description", "unit"]
            if fields is None
            else fields,
        }
        selected.update(mapping)
        if selected["action"] != "create":
            selected.pop("position", None)
        return {
            "job_id": str(self.job.pk),
            "draft_id": str(self.draft.pk),
            "result_revision": self.review["result_revision"],
            "expected_draft_revision": self.review["draft_revision"],
            "operation_key": str(uuid4()),
            "mappings": [selected],
        }

    def post(self, body, *, path=None):
        return self.client.post(
            path or self.apply_url,
            body,
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf,
        )

    def snapshot(self):
        self.draft.refresh_from_db()
        return (
            draft_revision(self.draft),
            list(
                DraftOrderLine.objects.filter(order=self.draft)
                .order_by("position")
                .values(
                    "id",
                    "position",
                    "requested_sku",
                    "requested_description",
                    "quantity",
                    "unit",
                    "catalogue_item_id",
                    "catalogue_sku_snapshot",
                    "catalogue_description_snapshot",
                    "updated_at",
                )
            ),
            self.application_count(),
        )

    def manual_line(self, *, position=7, attached=False):
        item = (
            CatalogItem.objects.create(
                organization=self.organization,
                sku="CAT-0001",
                description="Catalogue snapshot",
            )
            if attached
            else None
        )
        return DraftOrderLine.objects.create(
            organization=self.organization,
            order=self.draft,
            position=position,
            requested_sku="Manual-SKU",
            requested_description="Manual description",
            quantity=Decimal("2.125"),
            unit="box",
            catalogue_item=item,
            catalogue_sku_snapshot=item.sku if item else "",
            catalogue_description_snapshot=item.description if item else "",
        )

    def fresh_payload(self, **kwargs):
        response = self.client.get(self.review_url)
        self.assertEqual(response.status_code, 200, response.content)
        self.review = response.json()
        return self.payload(**kwargs)

    def assert_clean_scope(self):
        self.assertFalse(connection.in_atomic_block)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT NULLIF(current_setting("
                "'orderdesk.organization_id', true), ''), "
                "NULLIF(current_setting('orderdesk.user_id', true), '')"
            )
            self.assertEqual(cursor.fetchone(), (None, None))

    def test_review_is_read_only_stable_and_retains_raw_provenance(self):
        self.ready()
        before = self.snapshot()
        first = self.review
        second = self.client.get(self.review_url).json()
        self.assertEqual(first, second)
        self.assertRegex(first["result_revision"], r"^[a-f0-9]{64}$")
        self.assertEqual(first["draft_revision"], draft_revision(self.draft))
        self.assertEqual(first["draft"]["id"], str(self.draft.pk))
        self.assertEqual(first["count"], 1)
        self.assertEqual(first["reviewed_fields"], [])
        fields = first["results"][0]["fields"]
        self.assertEqual(fields["sku"]["raw"], "0001.Mixed-Case")
        self.assertEqual(fields["sku"]["row"], 2)
        self.assertEqual(fields["sku"]["column_index"], 1)
        self.assertEqual(fields["quantity"]["value"], "1.234")
        self.assertEqual(self.snapshot(), before)

    def test_admin_and_reviewer_create_selected_line_with_exact_values(self):
        self.ready()
        for role in (MembershipRole.ADMIN, MembershipRole.REVIEWER):
            with self.subTest(role=role):
                Membership.objects.filter(user=self.user).update(role=role)
                self.draft = DraftOrder.objects.create(
                    organization=self.organization, initiating_user=self.user
                )
                self.review_url = self.extraction + f"review/?draft_id={self.draft.pk}"
                body = self.fresh_payload()
                initial_updated = self.draft.updated_at
                response = self.post(body)
                self.assertEqual(response.status_code, 201, response.content)
                result = response.json()
                line = DraftOrderLine.objects.get(order=self.draft)
                self.assertEqual(line.requested_sku, "0001.Mixed-Case")
                self.assertEqual(line.requested_description, "Source description")
                self.assertEqual(line.quantity, Decimal("1.234"))
                self.assertEqual(line.unit, "ea")
                self.assertIsNone(line.catalogue_item_id)
                self.assertEqual(result["decisions"][0]["line_id"], str(line.pk))
                self.assertTrue(result["review_complete"])
                self.draft.refresh_from_db()
                self.assertGreater(self.draft.updated_at, initial_updated)
                self.assertEqual(result["revision"], draft_revision(self.draft))
                self.assert_clean_scope()

    def test_correction_is_explicit_and_raw_job_result_is_immutable(self):
        self.ready()
        self.job.refresh_from_db()
        immutable = deepcopy(self.job.result)
        body = self.payload(corrections={"sku": "0002.Deliberate", "quantity": "2.500"})
        response = self.post(body)
        self.assertEqual(response.status_code, 201, response.content)
        fields = response.json()["decisions"][0]["fields"]
        self.assertEqual(fields["sku"]["source"], immutable[0]["sku"])
        self.assertEqual(fields["sku"]["value"], "0002.Deliberate")
        self.assertTrue(fields["sku"]["corrected"])
        self.assertFalse(fields["description"]["corrected"])
        self.assertEqual(fields["quantity"]["source"]["value"], "1.234")
        line = DraftOrderLine.objects.get(order=self.draft)
        self.assertEqual(line.quantity, Decimal("2.500"))
        self.job.refresh_from_db()
        self.assertEqual(self.job.result, immutable)

    def test_explicit_existing_line_update_preserves_unselected_and_manual_lines(self):
        self.ready()
        target = self.manual_line(attached=True)
        untouched = self.manual_line(position=12)
        original_untouched = (
            DraftOrderLine.objects.filter(pk=untouched.pk).values().get()
        )
        response = self.post(
            self.fresh_payload(fields=["sku"], action="update", line_id=str(target.pk))
        )
        self.assertEqual(response.status_code, 201, response.content)
        target.refresh_from_db()
        self.assertEqual(target.requested_sku, "0001.Mixed-Case")
        self.assertEqual(target.requested_description, "Manual description")
        self.assertEqual(target.quantity, Decimal("2.125"))
        self.assertEqual(target.unit, "box")
        self.assertIsNotNone(target.catalogue_item_id)
        self.assertEqual(target.catalogue_sku_snapshot, "CAT-0001")
        self.assertEqual(
            DraftOrderLine.objects.filter(pk=untouched.pk).values().get(),
            original_untouched,
        )
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.customer_name, "Synthetic buyer")
        self.assertEqual(self.draft.customer_reference, "Manual reference")
        self.assertEqual(
            self.draft.original_intake_text, "Manual intake remains intact"
        )
        self.assertEqual(DraftOrderLine.objects.filter(order=self.draft).count(), 2)
        self.assertFalse(response.json()["review_complete"])

    def test_partial_acceptance_and_rejection_do_not_approve_or_convert(self):
        self.ready()
        first = self.post(self.payload(fields=["sku", "quantity"]))
        self.assertEqual(first.status_code, 201, first.content)
        self.assertFalse(first.json()["review_complete"])
        before = self.snapshot()
        second = self.post(
            self.fresh_payload(fields=["description", "unit"], action="reject")
        )
        self.assertEqual(second.status_code, 201, second.content)
        self.assertTrue(second.json()["review_complete"])
        self.assertEqual(self.snapshot()[:2], before[:2])
        self.assertEqual(self.application_count(), 2)
        reviewed = self.client.get(self.review_url).json()["reviewed_fields"]
        self.assertEqual(
            set(reviewed[0]["fields"]), set(self.review["results"][0]["fields"])
        )
        self.assertEqual(
            OrderDocument.objects.get(pk=self.document["id"]).status, "received"
        )
        self.assertEqual(self.order.documents.get().reviews.count(), 0)
        self.assertEqual(
            PurchaseOrder.objects.filter(source_draft=self.draft).count(), 0
        )
        self.assertEqual(self.draft.status, "draft")
        readiness = self.client.get(self.detail + "readiness/").json()
        self.assertFalse(readiness["ready_to_convert"])

    def test_rejection_only_does_not_advance_draft_revision(self):
        self.ready()
        original = self.snapshot()
        response = self.post(self.payload(action="reject"))
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["revision"], original[0])
        self.assertTrue(response.json()["review_complete"])
        self.assertEqual(self.snapshot()[:2], original[:2])

    def test_same_key_same_payload_replays_committed_response_without_writes(self):
        self.ready()
        body = self.payload()
        first = self.post(body)
        self.assertEqual(first.status_code, 201, first.content)
        committed = self.snapshot()
        with (
            patch.object(DraftOrderLine, "save") as line_save,
            patch.object(DraftOrder, "save") as draft_save,
        ):
            replay = self.post(body)
        self.assertEqual(replay.status_code, 200, replay.content)
        self.assertEqual(replay.json(), first.json())
        line_save.assert_not_called()
        draft_save.assert_not_called()
        self.assertEqual(self.snapshot(), committed)

    def test_key_reuse_with_changed_payload_conflicts(self):
        self.ready()
        body = self.payload()
        self.assertEqual(self.post(body).status_code, 201)
        before = self.snapshot()
        for changed in (
            {"expected_draft_revision": "0" * 64},
            {"result_revision": "0" * 64},
            {"mappings": [{**body["mappings"][0], "corrections": {"sku": "Other"}}]},
        ):
            with self.subTest(changed=changed):
                response = self.post({**body, **changed})
                self.assertEqual(response.status_code, 409, response.content)
                self.assertEqual(self.snapshot(), before)

    def test_normalized_selection_order_replays_the_same_operation(self):
        self.ready()
        body = self.payload(corrections={"quantity": "2.500", "sku": "Deliberate"})
        first = self.post(body)
        self.assertEqual(first.status_code, 201, first.content)
        before = self.snapshot()
        reordered = deepcopy(body)
        reordered["mappings"][0]["fields"].reverse()
        reordered["mappings"][0]["corrections"] = {
            "sku": "Deliberate",
            "quantity": "2.500",
        }
        replay = self.post(reordered)
        self.assertEqual(replay.status_code, 200, replay.content)
        self.assertEqual(replay.json(), first.json())
        self.assertEqual(self.snapshot(), before)

    def test_replay_preserves_later_manual_correction_and_original_revision(self):
        self.ready()
        body = self.payload()
        first = self.post(body)
        self.assertEqual(first.status_code, 201, first.content)
        line = DraftOrderLine.objects.get(order=self.draft)
        current = self.client.get(self.review_url).json()["draft_revision"]
        changed = self.client.patch(
            self.detail + f"lines/{line.pk}/",
            {"requested_sku": "Later-Manual-Correction"},
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf,
            HTTP_IF_MATCH=f'"{current}"',
        )
        self.assertEqual(changed.status_code, 200, changed.content)
        before = self.snapshot()
        replay = self.post(body)
        self.assertEqual(replay.status_code, 200, replay.content)
        self.assertEqual(replay.json(), first.json())
        self.assertEqual(self.snapshot(), before)
        self.assertNotEqual(replay.json()["revision"], before[0])
        line.refresh_from_db()
        self.assertEqual(line.requested_sku, "Later-Manual-Correction")

    def test_different_key_cannot_recreate_applied_source_row(self):
        self.ready()
        self.assertEqual(self.post(self.payload()).status_code, 201)
        before = self.snapshot()
        response = self.post(self.fresh_payload(position=2))
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(self.snapshot(), before)
        line = DraftOrderLine.objects.get(order=self.draft)
        update = self.post(
            self.fresh_payload(
                fields=["quantity"],
                action="update",
                line_id=str(line.pk),
                corrections={"quantity": "3.125"},
            )
        )
        self.assertEqual(update.status_code, 201, update.content)
        line.refresh_from_db()
        self.assertEqual(line.quantity, Decimal("3.125"))
        self.assertEqual(DraftOrderLine.objects.filter(order=self.draft).count(), 1)

    def test_empty_unknown_ownership_and_invalid_mapping_shapes_do_not_write(self):
        self.ready()
        valid = self.payload()
        variants = [
            {},
            {**valid, "mappings": []},
            {**valid, "organization_id": str(self.organization.pk)},
            {**valid, "actor_id": str(self.user.pk)},
            {**valid, "status": "accepted"},
            {**valid, "operation_key": "unbounded-arbitrary-key"},
            {**valid, "expected_draft_revision": "invalid"},
            {**valid, "result_revision": "invalid"},
        ]
        for change in (
            {"fields": []},
            {"fields": ["sku", "sku"]},
            {"fields": ["sku", "customer_name"]},
            {"fields": "sku"},
            {"candidate_id": str(uuid4())},
            {"candidate_id": "invalid"},
            {"action": "approve"},
            {"position": 0},
            {"position": True},
            {"line_id": str(uuid4())},
            {"raw": "Forged provenance"},
            {"corrections": {"customer_name": "Forged"}},
            {"corrections": {"sku": 123}},
            {"corrections": {"sku": None}},
        ):
            variants.append({**valid, "mappings": [{**valid["mappings"][0], **change}]})
        before = self.snapshot()
        for body in variants:
            with (
                self.subTest(body=body),
                patch.object(DraftOrderLine, "save") as save,
            ):
                response = self.post(body)
            self.assertEqual(response.status_code, 400, response.content)
            save.assert_not_called()
            self.assertEqual(self.snapshot(), before)

    def test_conflicting_candidate_and_target_mappings_are_rejected(self):
        self.ready(b"sku,quantity\nA,1\nB,2\n")
        first = self.payload(fields=["sku", "quantity"])
        duplicate = deepcopy(first)
        duplicate["mappings"].append({**duplicate["mappings"][0], "position": 2})
        line = self.manual_line()
        one_target = self.fresh_payload(
            fields=["sku"], action="update", line_id=str(line.pk)
        )
        one_target["mappings"].append(
            {
                "candidate_id": self.review["results"][1]["candidate_id"],
                "action": "update",
                "fields": ["quantity"],
                "line_id": str(line.pk),
            }
        )
        repeated_position = self.fresh_payload(fields=["sku", "quantity"])
        repeated_position["mappings"].append(
            {
                "candidate_id": self.review["results"][1]["candidate_id"],
                "action": "create",
                "fields": ["sku", "quantity"],
                "position": 1,
            }
        )
        before = self.snapshot()
        for body in (duplicate, one_target, repeated_position):
            with self.subTest(body=body):
                response = self.post(body)
                self.assertEqual(response.status_code, 400, response.content)
                self.assertEqual(self.snapshot(), before)

    def test_unselected_correction_and_blank_required_identity_are_invalid(self):
        self.ready()
        before = self.snapshot()
        for body in (
            self.payload(fields=["sku"], corrections={"quantity": "2.000"}),
            self.payload(corrections={"sku": "", "description": ""}),
            self.payload(corrections={"sku": " ", "description": "\u2003"}),
            self.payload(corrections={"unit": "x" * 33}),
        ):
            with self.subTest(body=body):
                response = self.post(body)
                self.assertEqual(response.status_code, 400, response.content)
                self.assertEqual(self.snapshot(), before)

    def test_draft_decimal_precision_is_exact_and_never_rounded(self):
        self.ready(b"sku,quantity\n0001,1.2345\n")
        before = self.snapshot()
        rejected = self.post(self.payload(fields=["sku", "quantity"]))
        self.assertEqual(rejected.status_code, 400, rejected.content)
        self.assertEqual(self.snapshot(), before)
        for invalid in (
            "1.0001",
            "1000000000",
            "0",
            "-1",
            "1e2",
            "NaN",
            "Infinity",
            "1,5",
            "",
        ):
            with self.subTest(value=invalid):
                response = self.post(
                    self.payload(
                        fields=["sku", "quantity"], corrections={"quantity": invalid}
                    )
                )
                self.assertEqual(response.status_code, 400, response.content)
                self.assertEqual(self.snapshot(), before)
        accepted = self.post(
            self.payload(fields=["sku", "quantity"], corrections={"quantity": "1.234"})
        )
        self.assertEqual(accepted.status_code, 201, accepted.content)
        self.assertEqual(
            DraftOrderLine.objects.get(order=self.draft).quantity, Decimal("1.234")
        )
        self.job.refresh_from_db()
        self.assertEqual(self.job.result[0]["quantity"]["value"], "1.2345")

    def test_empty_optional_corrections_and_maximum_decimal_are_preserved(self):
        self.ready()
        body = self.payload(
            corrections={"quantity": "999999999.999", "description": "", "unit": ""}
        )
        response = self.post(body)
        self.assertEqual(response.status_code, 201, response.content)
        line = DraftOrderLine.objects.get(order=self.draft)
        self.assertEqual(line.quantity, Decimal("999999999.999"))
        self.assertEqual(line.requested_description, "")
        self.assertEqual(line.unit, "")
        fields = response.json()["decisions"][0]["fields"]
        self.assertTrue(fields["description"]["corrected"])
        self.assertEqual(fields["description"]["source"]["value"], "Source description")

    def test_mapping_request_is_bounded_to_fifty_rows(self):
        self.ready(b"sku,quantity\n" + b"A,1\n" * 51)
        body = self.payload(fields=["sku", "quantity"])
        second = self.client.get(self.review_url + "&page=2").json()
        rows = [*self.review["results"], *second["results"]]
        body["mappings"] = [
            {
                "candidate_id": row["candidate_id"],
                "action": "create",
                "position": index + 1,
                "fields": ["sku", "quantity"],
            }
            for index, row in enumerate(rows)
        ]
        before = self.snapshot()
        response = self.post(body)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(self.snapshot(), before)

    def test_stale_source_result_and_draft_are_rejected_without_writes(self):
        self.ready()
        body = self.payload()
        before = self.snapshot()
        stale_result = self.post({**body, "result_revision": "0" * 64})
        self.assertEqual(stale_result.status_code, 409, stale_result.content)
        self.assertEqual(self.snapshot(), before)
        OrderDocument.objects.filter(pk=self.document["id"]).update(
            source_sha256="0" * 64
        )
        stale_source = self.post(body)
        self.assertEqual(stale_source.status_code, 409, stale_source.content)
        self.assertEqual(self.snapshot(), before)
        OrderDocument.objects.filter(pk=self.document["id"]).update(
            source_sha256=self.job.source_sha256
        )
        self.manual_line()
        before = self.snapshot()
        stale_draft = self.post(body)
        self.assertEqual(stale_draft.status_code, 412, stale_draft.content)
        self.assertEqual(self.snapshot(), before)

    def test_failed_and_queued_results_cannot_be_partially_applied(self):
        self.ready()
        body = self.payload()
        uploaded = self.upload(b"sku,quantity\nA,1\nB,invalid\n", "invalid.csv")
        path = uploaded.json()["extraction_url"]
        queued = self.client.post(path, {}, format="json", HTTP_X_CSRFTOKEN=self.csrf)
        body["job_id"] = queued.json()["id"]
        before = self.snapshot()
        self.assertEqual(self.post(body, path=path + "apply/").status_code, 409)
        job = DocumentExtractionJob.objects.get(pk=body["job_id"])
        self.assertEqual(
            process_extraction(
                actor=self.user, organization_id=self.organization.pk, job_id=job.pk
            ),
            "failed",
        )
        self.assertEqual(self.post(body, path=path + "apply/").status_code, 409)
        self.assertEqual(
            self.client.get(path + f"review/?draft_id={self.draft.pk}").status_code,
            409,
        )
        self.assertEqual(self.snapshot(), before)
        job.refresh_from_db()
        self.assertEqual(job.result, [])

    def test_receipt_validation_failure_rolls_back_all_lines_and_revision(self):
        self.ready()
        before = self.snapshot()
        with patch(
            "apps.orders.extraction_apply.ExtractionApplication.objects.create",
            side_effect=ValidationError(
                {
                    "operation_key": ["Synthetic field error."],
                    "__all__": ["Synthetic error."],
                }
            ),
        ):
            response = self.post(self.payload())
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()["operation_key"], ["Synthetic field error."])
        self.assertEqual(response.json()["non_field_errors"], ["Synthetic error."])
        self.assertNotIn("__all__", response.json())
        self.assertEqual(self.snapshot(), before)
        self.assert_clean_scope()

    def test_error_after_first_line_write_rolls_back_entire_application(self):
        self.ready(b"sku,quantity\nA,1\nB,2\n")
        body = self.payload(fields=["sku", "quantity"])
        body["mappings"].append(
            {
                "candidate_id": self.review["results"][1]["candidate_id"],
                "action": "create",
                "position": 2,
                "fields": ["sku", "quantity"],
            }
        )
        before = self.snapshot()
        original = DraftOrderLine.save
        calls = 0

        def fail_second(line, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ValidationError({"quantity": ["Synthetic save failure."]})
            return original(line, *args, **kwargs)

        with patch.object(DraftOrderLine, "save", fail_second):
            response = self.post(body)
        self.assertEqual(calls, 2)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("quantity", response.json())
        self.assertEqual(self.snapshot(), before)
        self.assert_clean_scope()

    def test_full_clean_error_is_a_stable_400_without_partial_writes(self):
        self.ready()
        before = self.snapshot()
        with patch.object(
            DraftOrderLine,
            "full_clean",
            side_effect=ValidationError({"__all__": ["Synthetic constraint failure."]}),
        ):
            response = self.post(self.payload())
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(
            response.json()["non_field_errors"], ["Synthetic constraint failure."]
        )
        self.assertEqual(self.snapshot(), before)
        self.assert_clean_scope()

    def test_csrf_missing_invalid_unauthenticated_and_viewer_are_denied(self):
        self.ready()
        before = self.snapshot()
        for headers in ({}, {"HTTP_X_CSRFTOKEN": "invalid"}):
            with self.subTest(headers=headers):
                response = self.client.post(
                    self.apply_url, self.payload(), format="json", **headers
                )
                self.assertEqual(response.status_code, 403)
        self.assertEqual(
            APIClient().post(self.apply_url, self.payload(), format="json").status_code,
            403,
        )
        Membership.objects.filter(user=self.user).update(role=MembershipRole.VIEWER)
        self.assertEqual(self.client.get(self.review_url).status_code, 200)
        self.assertEqual(self.post(self.payload()).status_code, 403)
        self.assertEqual(self.snapshot(), before)

    def test_inactive_removed_never_member_and_inactive_workspace_are_denied(self):
        self.ready()
        before = self.snapshot()
        membership = Membership.objects.get(user=self.user)
        for model, pk in (
            (Membership, membership.pk),
            (User, self.user.pk),
            (Organization, self.organization.pk),
        ):
            with self.subTest(model=model.__name__):
                model.objects.filter(pk=pk).update(is_active=False)
                self.assertEqual(self.post(self.payload()).status_code, 403)
                self.assertEqual(self.client.get(self.review_url).status_code, 403)
                model.objects.filter(pk=pk).update(is_active=True)
                self.assertEqual(self.snapshot(), before)
        membership.delete()
        self.assertEqual(self.post(self.payload()).status_code, 403)
        outsider = User.objects.create_superuser(
            email="apply-outsider@example.test", password="synthetic-apply-password"
        )
        self.client.force_login(outsider)
        self.csrf = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        self.assertEqual(self.post(self.payload()).status_code, 403)
        self.assertEqual(self.client.get(self.review_url).status_code, 403)
        self.assertEqual(self.snapshot(), before)

    def test_revocation_between_permission_and_transaction_denies_application(self):
        self.ready()
        before = self.snapshot()

        def revoke(**kwargs):
            context = resolve_workspace_context(**kwargs)
            Membership.objects.filter(user=self.user).update(is_active=False)
            return context

        with patch(
            "apps.organizations.permissions.resolve_workspace_context",
            side_effect=revoke,
        ):
            response = self.post(self.payload())
        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(self.snapshot(), before)
        self.assert_clean_scope()

    def test_replay_requires_fresh_writer_authorization(self):
        self.ready()
        body = self.payload()
        self.assertEqual(self.post(body).status_code, 201)
        before = self.snapshot()
        Membership.objects.filter(user=self.user).update(role=MembershipRole.VIEWER)
        self.assertEqual(self.post(body).status_code, 403)
        Membership.objects.filter(user=self.user).update(
            role=MembershipRole.ADMIN, is_active=False
        )
        self.assertEqual(self.post(body).status_code, 403)
        self.assertEqual(self.snapshot(), before)

    def test_cross_tenant_draft_line_and_job_do_not_leak_or_mutate(self):
        self.ready()
        foreign = create_organization(actor=self.user, name="Foreign apply tenant")
        draft = DraftOrder.objects.create(
            organization=foreign, initiating_user=self.user
        )
        line = DraftOrderLine.objects.create(
            organization=foreign, order=draft, position=1, requested_sku="FOREIGN"
        )
        before = self.snapshot()
        for draft_id in (draft.pk, uuid4()):
            with self.subTest(draft_id=draft_id):
                body = self.payload()
                body["draft_id"] = str(draft_id)
                self.assertEqual(self.post(body).status_code, 404)
                self.assertEqual(
                    self.client.get(
                        self.extraction + f"review/?draft_id={draft_id}"
                    ).status_code,
                    404,
                )
        target_errors = []
        for line_id in (line.pk, uuid4()):
            with self.subTest(line_id=line_id):
                response = self.post(
                    self.payload(action="update", line_id=str(line_id))
                )
                self.assertEqual(response.status_code, 400, response.content)
                target_errors.append(response.json())
        self.assertEqual(target_errors[0], target_errors[1])
        unknown_job = self.payload()
        unknown_job["job_id"] = str(uuid4())
        self.assertEqual(self.post(unknown_job).status_code, 404)
        self.assertEqual(self.snapshot(), before)
        line.refresh_from_db()
        self.assertEqual(line.requested_sku, "FOREIGN")

    def test_review_pagination_and_boundaries(self):
        self.ready(b"sku,quantity\n" + b"A,1\n" * 51)
        self.assertEqual(self.review["count"], 51)
        self.assertEqual(len(self.review["results"]), 50)
        second = self.client.get(self.review_url + "&page=2")
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(len(second.json()["results"]), 1)
        first_ids = {row["candidate_id"] for row in self.review["results"]}
        self.assertNotIn(second.json()["results"][0]["candidate_id"], first_ids)
        self.assertEqual(
            self.client.get(self.review_url + "&page_size=1000").status_code, 400
        )
        for method in ("put", "patch", "delete"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    self.apply_url, {}, format="json", HTTP_X_CSRFTOKEN=self.csrf
                )
                self.assertEqual(response.status_code, 405)

    def _thread_request(
        self, *, barrier=None, method="post", path=None, body=None, revision=None
    ):
        close_old_connections()
        try:
            client = APIClient(enforce_csrf_checks=True)
            client.force_login(User.objects.get(pk=self.user.pk))
            token = client.get("/api/v1/auth/csrf/").json()["csrf_token"]
            headers = {"HTTP_X_CSRFTOKEN": token}
            if revision is not None:
                headers["HTTP_IF_MATCH"] = f'"{revision}"'
            if barrier is not None:
                barrier.wait()
            response = getattr(client, method)(
                path or self.apply_url,
                body,
                format="json",
                **headers,
            )
            self.assert_clean_scope()
            return response.status_code, response.json()
        finally:
            connections["default"].close()

    def test_concurrent_same_operation_key_commits_once_and_replays(self):
        self.ready()
        body = self.payload()
        barrier = Barrier(2, timeout=10)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(self._thread_request, barrier=barrier, body=body)
                for _ in range(2)
            ]
            outcomes = [future.result(timeout=20) for future in futures]
        self.assertCountEqual([status for status, _ in outcomes], [201, 200])
        self.assertEqual(outcomes[0][1], outcomes[1][1])
        self.assertEqual(DraftOrderLine.objects.filter(order=self.draft).count(), 1)
        self.assertEqual(self.application_count(), 1)
        self.assert_clean_scope()

    def test_competing_application_keys_cannot_overwrite_or_duplicate(self):
        self.ready()
        barrier = Barrier(2, timeout=10)
        bodies = [self.payload(), self.payload(corrections={"sku": "Explicit-other"})]
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(self._thread_request, barrier=barrier, body=body)
                for body in bodies
            ]
            outcomes = [future.result(timeout=20) for future in futures]
        statuses = [status for status, _ in outcomes]
        self.assertEqual(statuses.count(201), 1)
        self.assertIn(next(status for status in statuses if status != 201), (409, 412))
        self.assertEqual(DraftOrderLine.objects.filter(order=self.draft).count(), 1)
        self.assertEqual(self.application_count(), 1)

    def test_application_and_manual_edit_use_one_aggregate_revision(self):
        self.ready()
        body = self.payload()
        revision = body["expected_draft_revision"]
        barrier = Barrier(2, timeout=10)
        with ThreadPoolExecutor(max_workers=2) as pool:
            applying = pool.submit(self._thread_request, barrier=barrier, body=body)
            editing = pool.submit(
                self._thread_request,
                barrier=barrier,
                method="patch",
                path=self.detail,
                body={"customer_name": "Concurrent manual buyer"},
                revision=revision,
            )
            applied = applying.result(timeout=20)
            edited = editing.result(timeout=20)
        self.assertIn((applied[0], edited[0]), ((201, 412), (412, 200)))
        self.draft.refresh_from_db()
        if applied[0] == 201:
            self.assertEqual(self.draft.customer_name, "Synthetic buyer")
            self.assertEqual(DraftOrderLine.objects.filter(order=self.draft).count(), 1)
        else:
            self.assertEqual(self.draft.customer_name, "Concurrent manual buyer")
            self.assertEqual(DraftOrderLine.objects.filter(order=self.draft).count(), 0)

    def test_application_and_conversion_cannot_use_an_obsolete_edit(self):
        self.ready()
        line = self.manual_line(attached=True)
        body = self.fresh_payload(
            fields=["quantity"],
            action="update",
            line_id=str(line.pk),
            corrections={"quantity": "3.500"},
        )
        revision = body["expected_draft_revision"]
        barrier = Barrier(2, timeout=10)
        with ThreadPoolExecutor(max_workers=2) as pool:
            applying = pool.submit(self._thread_request, barrier=barrier, body=body)
            converting = pool.submit(
                self._thread_request,
                barrier=barrier,
                path=self.detail + "convert/",
                body={},
                revision=revision,
            )
            applied = applying.result(timeout=20)
            converted = converting.result(timeout=20)
        self.assertIn((applied[0], converted[0]), ((201, 412), (409, 201)))
        line.refresh_from_db()
        self.draft.refresh_from_db()
        if applied[0] == 201:
            self.assertEqual(line.quantity, Decimal("3.500"))
            self.assertEqual(self.draft.status, "draft")
            self.assertEqual(
                PurchaseOrder.objects.filter(source_draft=self.draft).count(), 0
            )
        else:
            self.assertEqual(line.quantity, Decimal("2.125"))
            self.assertEqual(self.draft.status, "converted")
            copied = PurchaseOrder.objects.get(source_draft=self.draft).lines.get()
            self.assertEqual(copied.quantity, Decimal("2.125"))
            self.assertEqual(self.application_count(), 0)

    def test_historical_replay_after_conversion_cannot_mutate_the_source(self):
        self.ready()
        line = self.manual_line(attached=True)
        body = self.fresh_payload(
            fields=["quantity"],
            action="update",
            line_id=str(line.pk),
            corrections={"quantity": "3.500"},
        )
        first = self.post(body)
        self.assertEqual(first.status_code, 201, first.content)
        converted = self.client.post(
            self.detail + "convert/",
            {},
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf,
            HTTP_IF_MATCH=f'"{first.json()["revision"]}"',
        )
        self.assertEqual(converted.status_code, 201, converted.content)
        before = self.snapshot()
        replay = self.post(body)
        self.assertEqual(replay.status_code, 200, replay.content)
        self.assertEqual(replay.json(), first.json())
        self.assertEqual(self.snapshot(), before)
        new = deepcopy(body)
        new["operation_key"] = str(uuid4())
        new["expected_draft_revision"] = before[0]
        self.assertEqual(self.post(new).status_code, 409)
        self.assertEqual(self.snapshot(), before)

    @staticmethod
    def _pid():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_catalog.pg_backend_pid()")
            return cursor.fetchone()[0]

    def _wait_for_block(self, waiter, blocker):
        deadline = monotonic() + 5
        pause = Event()
        while monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_catalog.pg_blocking_pids(%s)", [waiter])
                if blocker in cursor.fetchone()[0]:
                    return
            pause.wait(0.02)
        self.fail("Expected organization lock wait was not observed.")

    def test_committed_demotion_or_revocation_denies_waiting_application(self):
        self.ready()
        for change in ({"role": MembershipRole.VIEWER}, {"is_active": False}):
            with self.subTest(change=change):
                Membership.objects.filter(user=self.user).update(
                    role=MembershipRole.ADMIN, is_active=True
                )
                body = self.payload()
                ready = Queue()
                blocker = self._pid()

                def attempt(*, ready=ready, body=body):
                    close_old_connections()
                    observed = False

                    def inspect(execute, statement, params, many, context):
                        nonlocal observed
                        if (
                            not observed
                            and "organizations_organization" in statement
                            and "FOR UPDATE" in statement
                        ):
                            observed = True
                            ready.put(self._pid())
                        return execute(statement, params, many, context)

                    try:
                        with connection.execute_wrapper(inspect):
                            return self._thread_request(body=body)
                    finally:
                        connections["default"].close()

                with ThreadPoolExecutor(max_workers=1) as pool:
                    with transaction.atomic():
                        Organization.objects.select_for_update().get(
                            pk=self.organization.pk
                        )
                        Membership.objects.filter(user=self.user).update(**change)
                        future = pool.submit(attempt)
                        waiter = ready.get(timeout=10)
                        self._wait_for_block(waiter, blocker)
                    result = future.result(timeout=15)
                self.assertEqual(result[0], 403, result)
                self.assertEqual(self.application_count(), 0)
                self.assertEqual(
                    DraftOrderLine.objects.filter(order=self.draft).count(), 0
                )
                self.assert_clean_scope()
