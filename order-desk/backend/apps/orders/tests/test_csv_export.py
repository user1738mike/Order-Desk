"""Independent CSV expectations, protected API, real storage and commit races."""

import csv
import hashlib
import io
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import patch
from uuid import uuid4

from django.core.management import call_command
from django.db import DatabaseError, close_old_connections, connection, connections, transaction
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.orders import export_services, services
from apps.orders.csv_export import PROFILE, ExportBlocked, format_csv
from apps.orders.models import PurchaseOrder, PurchaseOrderExport, PurchaseOrderLine
from apps.orders.tests import test_draft_conversion as fixtures
from apps.organizations.models import MembershipRole


def independent_payload():
    return {"order_id": "11111111-1111-4111-8111-111111111111",
            "source_draft_id": "22222222-2222-4222-8222-222222222222",
            "order_number": "00042", "order_date": "2026-10-10",
            "customer_name": 'Buyer, "North"', "lines": [
                {"id": "33333333-3333-4333-8333-333333333333", "line_number": 7,
                 "sku": "0001.Mixed-Case", "description": 'Café, "widget"\r\ncontinued',
                 "quantity": "1.2340", "unit": ""}]}


class CSVProfileTests(SimpleTestCase):
    def test_independent_exact_bytes_and_roundtrip(self):
        expected = (
            'profile,order_id,source_draft_id,order_number,order_date,customer_name,line_number,sku,description,quantity,unit\r\n'
            'generic-po-csv-v1,11111111-1111-4111-8111-111111111111,22222222-2222-4222-8222-222222222222,00042,2026-10-10,"Buyer, ""North""",7,0001.Mixed-Case,"Café, ""widget""\r\ncontinued",1.2340,\r\n'
        ).encode("utf-8")
        actual = format_csv(independent_payload())
        self.assertEqual(actual, expected)
        rows = list(csv.DictReader(io.StringIO(actual.decode(), newline="")))
        self.assertEqual(rows[0]["sku"], "0001.Mixed-Case")
        self.assertEqual(rows[0]["quantity"], "1.2340")
        self.assertEqual(rows[0]["description"], 'Café, "widget"\r\ncontinued')
        self.assertEqual(rows[0]["unit"], "")
        self.assertFalse(actual.startswith(b"\xef\xbb\xbf"))

    def test_unsafe_and_unsupported_cells_do_not_mutate_source(self):
        for value, code in [("=SUM(1)", "unsafe_formula"), ("  '\"+code", "unsafe_formula"),
                            ("\u2003@code", "unsafe_formula"), ("-SKU", "unsafe_formula"),
                            ("\tSKU", "unsupported_control"), ("\ufeffSKU", "unsupported_control"),
                            ("plain\n=evil", "unsafe_formula"), ("x\x00y", "unsupported_control")]:
            with self.subTest(value=value):
                payload = independent_payload(); payload["lines"][0]["description"] = value
                with self.assertRaises(ExportBlocked) as caught:
                    format_csv(payload)
                self.assertEqual(caught.exception.blockers[0]["code"], code)
                self.assertEqual(payload["lines"][0]["description"], value)

    def test_missing_bounds_and_decimal_grammar(self):
        for quantity in ["0.0000", "-1.0000", "+1.0000", "1e2", "1.00000", "100000000000000.0000"]:
            with self.subTest(quantity=quantity):
                payload = independent_payload(); payload["lines"][0]["quantity"] = quantity
                with self.assertRaises(ExportBlocked): format_csv(payload)
        payload = independent_payload(); payload["lines"][0]["quantity"] = "99999999999999.9999"
        self.assertIn(b"99999999999999.9999", format_csv(payload))
        for mutation in [lambda p: p.update(customer_name=""), lambda p: p.update(lines=[]),
                         lambda p: p["lines"][0].update(description="x"*4097),
                         lambda p: p.update(lines=p["lines"]*501),
                         lambda p: p.update(lines=[{**p["lines"][0], "description":"é"*4096}]*500)]:
            payload = independent_payload(); mutation(payload)
            with self.assertRaises(ExportBlocked): format_csv(payload)


class CSVExportTests(TransactionTestCase):
    def setUp(self):
        fixtures.DraftConversionTests.setUp(self)
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        os.chmod(self.temp.name, 0o700)
        settings = override_settings(PRIVATE_DOCUMENT_ROOT=self.temp.name)
        settings.enable(); self.addCleanup(settings.disable)
        self.order = self.convert()
        services.submit_purchase_order_for_review(actor=self.user, organization_id=self.organization.pk, order_id=self.order.pk)
        services.approve_purchase_order(actor=self.user, organization_id=self.organization.pk, order_id=self.order.pk)
        self.base = f"/api/v1/workspaces/{self.organization.pk}/orders/{self.order.pk}/"
        self.exports = self.base + "exports/"

    def generate(self, **kwargs):
        return self.client.post(self.exports, kwargs.pop("body", {"profile":PROFILE}), format="json",
                                HTTP_X_CSRFTOKEN=self.token, **kwargs)

    def test_success_exact_download_replay_and_snapshot_independence(self):
        before = list(PurchaseOrderLine.objects.values())
        preview = self.client.get(self.exports)
        self.assertEqual(preview.status_code, 200, preview.content)
        self.assertTrue(preview.json()["eligible"])
        self.assertEqual(PurchaseOrderExport.objects.count(), 0)
        first = self.generate(); self.assertEqual(first.status_code, 201, first.content)
        data = first.json(); again = self.generate()
        self.assertEqual(again.status_code, 200, again.content)
        self.assertEqual(again.json(), data)
        self.item.description = "Changed live catalogue"; self.item.save()
        download = self.client.get(data["download_url"])
        self.assertEqual(download.status_code, 200)
        self.assertFalse(connection.in_atomic_block)
        content = b"".join(download.streaming_content); download.close()
        row = list(csv.DictReader(io.StringIO(content.decode(), newline="")))[0]
        self.assertEqual(row["sku"], "001-a/B"); self.assertEqual(row["quantity"], "2.1250")
        self.assertEqual(row["customer_name"], " Buyer ")
        self.assertEqual(row["description"], "Historical description")
        self.assertEqual(hashlib.sha256(content).hexdigest(), data["sha256"])
        self.assertEqual(len(content), data["size_bytes"])
        self.assertIn("attachment", download["Content-Disposition"])
        self.assertEqual(download["X-Content-Type-Options"], "nosniff")
        self.assertEqual(download["Cache-Control"], "private, no-store")
        self.assertEqual(before, list(PurchaseOrderLine.objects.values()))
        self.assertEqual(PurchaseOrderExport.objects.count(), 1)

    def test_fresh_export_role_csrf_and_inactive_boundaries(self):
        first = self.generate().json()
        for role, expected in [(MembershipRole.REVIEWER, 200), (MembershipRole.VIEWER, 403)]:
            with self.subTest(role=role):
                self.membership.role=role; self.membership.save()
                self.assertEqual(self.client.get(self.exports).status_code, expected)
                self.assertEqual(self.generate().status_code, expected)
                response=self.client.get(first["download_url"]); self.assertEqual(response.status_code, expected); response.close()
        self.membership.role=MembershipRole.ADMIN; self.membership.save()
        self.assertEqual(self.client.post(self.exports, {"profile":PROFILE}, format="json").status_code, 403)
        self.assertEqual(APIClient().get(self.exports).status_code, 403)
        for obj in (self.membership, self.user, self.organization):
            with self.subTest(type=type(obj).__name__):
                obj.is_active=False; obj.save()
                self.assertEqual(self.generate().status_code, 403)
                obj.is_active=True; obj.save()
        self.membership.delete()
        self.assertEqual(self.client.get(first["download_url"]).status_code, 403)

    def test_strict_input_methods_and_foreign_ids(self):
        for body in [{}, {"profile":"v2"}, {"profile":PROFILE,"storage_key":"x"}, [], {"profile":1}]:
            with self.subTest(body=body): self.assertEqual(self.generate(body=body).status_code, 400)
        for query in ["?x=1", "?profile=v2", "?page=1&page=2", "?profile=generic-po-csv-v1&profile=generic-po-csv-v1"]:
            self.assertEqual(self.client.get(self.exports+query).status_code, 400)
        self.assertEqual(PurchaseOrderExport.objects.count(), 0)
        for method in ("put","patch","delete"):
            self.assertEqual(getattr(self.client, method)(self.exports, {}, format="json", HTTP_X_CSRFTOKEN=self.token).status_code, 405)
        for value in (str(uuid4()), "malformed"):
            self.assertEqual(self.client.get(self.base+f"exports/{value}/download/").status_code,404)

    def test_not_approved_not_converted_or_inactive_are_blocked(self):
        legacy = services.create_purchase_order(actor=self.user, organization_id=self.organization.pk, customer_name="Legacy", purchase_order_number="LEGACY")
        path = f"/api/v1/workspaces/{self.organization.pk}/orders/{legacy.pk}/exports/"
        self.assertIn("not_converted", str(self.client.get(path).json()["blocking_reasons"]))
        PurchaseOrder.objects.filter(pk=self.order.pk).update(is_active=False)
        self.assertEqual(self.generate().status_code,400)
        self.assertEqual(PurchaseOrderExport.objects.count(),0)

    def test_approved_decision_lines_and_success_records_are_database_immutable(self):
        self.generate(); record=PurchaseOrderExport.objects.get()
        for model, pk, changes in [(PurchaseOrder,self.order.pk,{"status":"rejected"}),
                                   (PurchaseOrder,self.order.pk,{"review_note":"rewrite"}),
                                   (PurchaseOrderLine,PurchaseOrderLine.objects.get().pk,{"sku":"rewrite"}),
                                   (PurchaseOrderExport,record.pk,{"sha256":"a"*64}),
                                   (PurchaseOrderExport,record.pk,{"payload":{}})]:
            with self.subTest(model=model.__name__,changes=changes):
                with self.assertRaises(DatabaseError), transaction.atomic(): model.objects.filter(pk=pk).update(**changes)
        self.assertFalse(connection.in_atomic_block)

    def test_missing_corrupt_success_never_regenerates_bytes(self):
        data=self.generate().json(); record=PurchaseOrderExport.objects.get()
        path=Path(self.temp.name)/record.storage_key.split("/")[1]
        os.chmod(path,0o600); path.write_bytes(b"x"*record.size_bytes); os.chmod(path,0o400)
        self.assertEqual(self.client.get(data["download_url"]).status_code,503)
        self.assertEqual(self.generate().status_code,503)
        path.unlink()
        self.assertEqual(self.client.get(data["download_url"]).status_code,503)
        self.assertEqual(self.generate().status_code,503)
        self.assertEqual(PurchaseOrderExport.objects.get().status,"succeeded")
        self.assertEqual(list(Path(self.temp.name).iterdir()),[])

    def test_storage_and_finalization_failures_cleanup_and_explicit_retry(self):
        with patch("apps.orders.export_services.staged_document",side_effect=OSError("synthetic")):
            self.assertEqual(self.generate().status_code,503)
        record=PurchaseOrderExport.objects.get(); self.assertEqual(record.status,"failed")
        self.assertEqual(self.generate().status_code,201)
        self.assertEqual(PurchaseOrderExport.objects.get().attempts,2)

    def test_commit_ack_loss_preserves_reconcilable_success(self):
        original=export_services.tenant_scope
        writes=0
        @contextmanager
        def scope(**kwargs):
            nonlocal writes
            with original(**kwargs) as context:
                yield context
            if kwargs.get("write"):
                writes+=1
                if writes==2: raise DatabaseError("Synthetic acknowledgment loss")
        with patch("apps.orders.export_services.tenant_scope",scope):
            self.assertEqual(self.generate().status_code,503)
        self.assertEqual(PurchaseOrderExport.objects.get().status,"succeeded")
        self.assertEqual(self.generate().status_code,200)
        self.assertEqual(len(list(Path(self.temp.name).iterdir())),1)

    def test_duplicate_connections_and_role_revocation_before_publication(self):
        entered, release=Event(),Event(); original=export_services.staged_document
        @contextmanager
        def staged(*args,**kwargs):
            with original(*args,**kwargs) as state:
                entered.set(); self.assertTrue(release.wait(15)); yield state
        def run():
            close_old_connections()
            try: return export_services.generate_export(actor=self.user, organization_id=self.organization.pk, order_id=self.order.pk,validate_input=lambda:None)
            finally: connections["default"].close()
        with patch("apps.orders.export_services.staged_document",staged), ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(run); self.assertTrue(entered.wait(15))
            try:
                self.assertEqual(self.generate().status_code,202)
            finally: release.set()
            self.assertEqual(future.result(timeout=15)[1],201)
        self.assertEqual(PurchaseOrderExport.objects.count(),1)
        self.assertEqual(self.generate().status_code,200)

    def test_actual_prepublication_revocation_deletes_staged_file(self):
        original=export_services.staged_document
        @contextmanager
        def staged(*args,**kwargs):
            with original(*args,**kwargs) as state:
                self.membership.is_active=False; self.membership.save(); yield state
        with patch("apps.orders.export_services.staged_document",staged):
            self.assertEqual(self.generate().status_code,403)
        self.assertEqual(list(Path(self.temp.name).iterdir()),[])
        self.assertEqual(PurchaseOrderExport.objects.get().status,"running")

    def test_expired_claim_recovery_and_completed_orphan_protection(self):
        with patch("apps.orders.export_services.staged_document",side_effect=RuntimeError("process stopped")):
            with self.assertRaises(RuntimeError): self.generate()
        record=PurchaseOrderExport.objects.get()
        # Maintenance fixture simulates elapsed time without bypassing a claim guard.
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE orders_purchaseorderexport DISABLE TRIGGER export_source_guard")
            try: PurchaseOrderExport.objects.filter(pk=record.pk).update(lease_expires_at=timezone.now()-timedelta(seconds=1))
            finally: cursor.execute("ALTER TABLE orders_purchaseorderexport ENABLE TRIGGER export_source_guard")
        data=self.generate(); self.assertEqual(data.status_code,201,data.content)
        record.refresh_from_db(); self.assertEqual(record.attempts,2)
        path=Path(self.temp.name)/record.storage_key.split("/")[1]
        os.utime(path,(1,1)); orphan=Path(self.temp.name)/uuid4().hex; orphan.write_bytes(b"orphan"); os.utime(orphan,(1,1))
        with override_settings(DEBUG=True): call_command("reconcile_private_documents",stdout=io.StringIO())
        self.assertTrue(path.exists()); self.assertFalse(orphan.exists())
