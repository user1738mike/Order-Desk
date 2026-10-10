"""Durable proposals, exact source provenance, leases and tenant-facing failures."""

import io
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, close_old_connections, connection
from django.test import TransactionTestCase, override_settings

from apps.accounts.models import User
from apps.orders.csv_extraction import ExtractionFailure, extract_csv
from apps.orders.extraction_services import process_extraction
from apps.orders.models import DocumentExtractionJob, PurchaseOrderLine
from apps.orders.tests import test_private_document_intake as fixtures
from apps.organizations.models import Membership, MembershipRole


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class CSVExtractionTests(TransactionTestCase):
    setUp = fixtures.PrivateDocumentIntakeTests.setUp
    upload = fixtures.PrivateDocumentIntakeTests.upload

    def source(self, raw=fixtures.CSV):
        response = self.upload(raw, "source.csv")
        self.assertEqual(response.status_code, 201, response.content)
        self.document = response.json()
        self.extraction = self.document["extraction_url"]

    def queue(self):
        response = self.client.post(
            self.extraction, {}, format="json", HTTP_X_CSRFTOKEN=self.csrf
        )
        self.assertIn(response.status_code, (200, 202), response.content)
        return response.json()

    def process(self, job):
        return process_extraction(
            actor=self.user, organization_id=self.organization.pk, job_id=job.pk
        )

    def test_repeat_safe_queue_and_provenance_without_order_or_review_writes(self):
        self.source()
        self.assertIsNone(self.client.get(self.extraction).json()["job"])
        first = self.queue()
        self.assertEqual(first["id"], self.queue()["id"])
        job = DocumentExtractionJob.objects.get()
        self.assertEqual(self.process(job), "succeeded")
        self.assertEqual(self.process(job), "succeeded")
        body = self.client.get(self.extraction).json()
        field = body["results"][0]["sku"]
        self.assertEqual(
            field,
            {
                "value": "0001.Mixed-Case",
                "raw": "0001.Mixed-Case",
                "row": 2,
                "end_row": 2,
                "column": "sku",
                "column_index": 1,
            },
        )
        self.assertEqual(body["results"][0]["quantity"]["value"], "1.234")
        self.assertEqual(body["job"]["status"], "succeeded")
        self.assertEqual(PurchaseOrderLine.objects.count(), 0)
        self.assertEqual(
            self.order.document_reviews.count()
            if hasattr(self.order, "document_reviews")
            else self.order.documents.get().reviews.count(),
            0,
        )
        self.assertEqual(self.order.documents.get().status, "received")
        self.assertFalse(connection.in_atomic_block)

    def test_exact_values_multiline_provenance_and_no_formula_execution(self):
        raw = (
            b'sku,quantity,description,unit\r\n0001,01.2500,"line one\r\n'
            b'=SUM(A1)",ea\r\n'
        )
        rows = extract_csv(io.BytesIO(raw))
        self.assertEqual(rows[0]["quantity"]["value"], "01.2500")
        self.assertEqual(rows[0]["description"]["end_row"], 3)
        self.assertIn("=SUM", rows[0]["description"]["value"])

    def test_invalid_contract_variants_have_stable_failure_and_no_partial_results(self):
        for raw, code in (
            (b"SKU,quantity\nA,1\n", "unsupported_headers"),
            (b"sku,sku,quantity\nA,A,1\n", "unsupported_headers"),
            (b"sku,quantity\nA,1\nB,1e2\n", "invalid_quantity"),
            (b"sku,quantity\nA,0\n", "invalid_quantity"),
            (b"sku,quantity\nA,-1\n", "invalid_quantity"),
            (b"sku,quantity\nA,1.12345\n", "invalid_quantity"),
            (b"sku,quantity\nA,NaN\n", "invalid_quantity"),
            (b"sku,quantity\n,1\n", "invalid_sku"),
            (b"sku,quantity\n", "empty_result"),
        ):
            with (
                self.subTest(code=code, raw=raw),
                self.assertRaises(ExtractionFailure) as error,
            ):
                extract_csv(io.BytesIO(raw))
            self.assertEqual(error.exception.code, code)

    def test_visible_failure_and_explicit_bounded_retry(self):
        self.source(b"sku,quantity\nA,1\nB,invalid\n")
        self.queue()
        job = DocumentExtractionJob.objects.get()
        for attempt in range(1, 4):
            self.assertEqual(self.process(job), "failed")
            body = self.client.get(self.extraction).json()
            self.assertEqual(body["job"]["error_code"], "invalid_quantity")
            self.assertEqual(body["job"]["error_row"], 3)
            self.assertEqual(body["results"], [])
            response = self.client.post(
                self.extraction + "retry/",
                {},
                format="json",
                HTTP_X_CSRFTOKEN=self.csrf,
            )
            self.assertEqual(response.status_code, 202 if attempt < 3 else 400)

    def test_storage_failure_has_safe_visible_code(self):
        self.source()
        self.queue()
        with patch(
            "apps.orders.extraction_services.open_document",
            side_effect=OSError("private secret"),
        ):
            self.assertEqual(
                self.process(DocumentExtractionJob.objects.get()), "failed"
            )
        body = self.client.get(self.extraction).json()
        self.assertEqual(body["job"]["error_code"], "source_unavailable")
        self.assertNotIn("private secret", str(body))

    def test_parsing_holds_no_transaction_and_locked_order_fails_completion(self):
        self.source()
        self.queue()

        def parse(source):
            self.assertFalse(connection.in_atomic_block)
            type(self.order).objects.filter(pk=self.order.pk).update(is_active=False)
            return extract_csv(source)

        with patch("apps.orders.extraction_services.extract_csv", side_effect=parse):
            self.assertEqual(
                self.process(DocumentExtractionJob.objects.get()), "failed"
            )
        self.assertEqual(DocumentExtractionJob.objects.get().error_code, "order_locked")

    def test_revocation_before_publish_leaves_recoverable_lease(self):
        self.source()
        self.queue()

        def parse(source):
            Membership.objects.filter(user=self.user).update(is_active=False)
            return extract_csv(source)

        with (
            patch("apps.orders.extraction_services.extract_csv", side_effect=parse),
            self.assertRaises(PermissionDenied),
        ):
            self.process(DocumentExtractionJob.objects.get())
        job = DocumentExtractionJob.objects.get()
        self.assertEqual(job.status, "running")
        self.assertEqual(job.result, [])
        self.assertFalse(connection.in_atomic_block)

    def test_interrupted_worker_and_expired_lease_recovery(self):
        self.source()
        self.queue()
        with (
            patch("apps.orders.extraction_services.LEASE_SECONDS", -1),
            patch(
                "apps.orders.extraction_services.extract_csv",
                side_effect=RuntimeError("interrupted"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.process(DocumentExtractionJob.objects.get())
        job = DocumentExtractionJob.objects.get()
        self.assertTrue(self.client.get(self.extraction).json()["job"]["lease_expired"])
        self.assertEqual(self.process(job), "succeeded")
        self.assertEqual(DocumentExtractionJob.objects.get().attempts, 2)

    def test_live_lease_and_replaced_worker_cannot_publish(self):
        self.source()
        self.queue()
        job = DocumentExtractionJob.objects.get()

        def replace(source):
            # Old claim has expired. A second processor wins and publishes.
            with (
                patch("apps.orders.extraction_services.LEASE_SECONDS", 120),
                patch(
                    "apps.orders.extraction_services.extract_csv",
                    side_effect=extract_csv,
                ),
            ):
                self.assertEqual(self.process(job), "succeeded")
            return extract_csv(source)

        with (
            patch("apps.orders.extraction_services.LEASE_SECONDS", -1),
            patch("apps.orders.extraction_services.extract_csv", side_effect=replace),
        ):
            self.assertEqual(self.process(job), "superseded")
        self.assertEqual(DocumentExtractionJob.objects.get().attempts, 2)

    def test_live_lease_is_not_claimed_twice(self):
        self.source()
        self.queue()
        job = DocumentExtractionJob.objects.get()

        def live(source):
            self.assertEqual(self.process(job), "leased")
            return extract_csv(source)

        with patch("apps.orders.extraction_services.extract_csv", side_effect=live):
            self.assertEqual(self.process(job), "succeeded")

    def test_concurrent_claims_publish_one_complete_result(self):
        self.source()
        self.queue()
        job = DocumentExtractionJob.objects.get()
        barrier = Barrier(2, timeout=10)

        def run():
            close_old_connections()
            try:
                actor = User.objects.get(pk=self.user.pk)
                barrier.wait()
                return process_extraction(
                    actor=actor, organization_id=self.organization.pk, job_id=job.pk
                )
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: run(), range(2)))
        self.assertIn("succeeded", outcomes)
        job.refresh_from_db()
        self.assertEqual(job.attempts, 1)
        self.assertEqual(len(job.result), 1)

    def test_csrf_roles_revoked_foreign_and_unknown_inputs(self):
        self.source()
        self.assertEqual(
            self.client.post(self.extraction, {}, format="json").status_code, 403
        )
        self.assertEqual(
            self.client.post(
                self.extraction,
                {"result": []},
                format="json",
                HTTP_X_CSRFTOKEN=self.csrf,
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.get(self.extraction + "?page_size=1000").status_code, 400
        )
        self.assertEqual(
            self.client.get(
                self.extraction.replace(self.document["id"], str(uuid4()))
            ).status_code,
            404,
        )
        Membership.objects.filter(user=self.user).update(role=MembershipRole.VIEWER)
        self.assertEqual(self.client.get(self.extraction).status_code, 200)
        self.assertEqual(
            self.client.post(
                self.extraction, {}, format="json", HTTP_X_CSRFTOKEN=self.csrf
            ).status_code,
            403,
        )
        Membership.objects.filter(user=self.user).update(is_active=False)
        self.assertEqual(self.client.get(self.extraction).status_code, 403)
        self.assertEqual(DocumentExtractionJob.objects.count(), 0)

    def test_pdf_uses_shared_lifecycle_and_csv_results_are_paginated(self):
        response = self.upload()
        path = response.json()["download_url"].replace("download/", "extraction/")
        self.assertEqual(
            self.client.post(
                path, {}, format="json", HTTP_X_CSRFTOKEN=self.csrf
            ).status_code,
            202,
        )
        # Text-PDF support extends enqueue eligibility. This old byte-only PDF
        # remains an invalid profile; it must fail visibly without proposals.
        pdf_job = DocumentExtractionJob.objects.get()
        self.assertEqual(self.process(pdf_job), "failed")
        pdf_job.refresh_from_db()
        self.assertEqual(pdf_job.result, [])
        self.assertFalse(self.client.get(path).json()["job"]["can_retry"])
        self.source(b"sku,quantity\n" + b"A,1\n" * 51)
        self.queue()
        self.process(DocumentExtractionJob.objects.get(document_id=self.document["id"]))
        body = self.client.get(self.extraction).json()
        self.assertEqual(body["count"], 51)
        self.assertEqual(len(body["results"]), 50)
        self.assertEqual(
            len(self.client.get(self.extraction + "?page=2").json()["results"]), 1
        )

    def test_row_result_limits_and_terminal_immutability(self):
        for raw, code in (
            (b"sku,quantity\n" + b"A,1\n" * 501, "row_limit"),
            (
                b"sku,quantity,description\n" + b"A,1," + b"x" * 4096 + b"\n",
                "result_limit",
            ),
        ):
            with (
                self.subTest(code=code),
                patch("apps.orders.csv_extraction.MAX_RESULT_BYTES", 100),
                self.assertRaises(ExtractionFailure) as error,
            ):
                extract_csv(io.BytesIO(raw))
            self.assertEqual(error.exception.code, code)
        self.source()
        self.queue()
        self.process(DocumentExtractionJob.objects.get())
        with self.assertRaises(IntegrityError):
            DocumentExtractionJob.objects.update(result=[])
