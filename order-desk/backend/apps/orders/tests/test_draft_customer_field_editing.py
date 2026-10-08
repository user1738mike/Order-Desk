"""PostgreSQL API tests for protected draft customer-field editing."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.orders.models import DraftOrder, DraftOrderLine
from apps.organizations.context import resolve_workspace_context
from apps.organizations.models import Membership, MembershipRole
from apps.organizations.selection import SELECTED_WORKSPACE_KEY
from apps.organizations.services import create_organization


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class DraftCustomerFieldEditingAPITests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="draft-create@example.test")
        self.organization = create_organization(
            actor=self.user, name="Draft Creation Workspace"
        )
        self.membership = Membership.objects.get(
            user=self.user, organization=self.organization
        )
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.force_login(self.user)
        self.url = f"/api/v1/workspaces/{self.organization.pk}/draft-orders/"
        self.csrf_token = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        self.collection_url = self.url
        self.draft = DraftOrder.objects.create(
            organization=self.organization,
            initiating_user=self.user,
            customer_name="Original customer",
            customer_reference="Original reference",
            original_intake_text="Original synthetic request",
        )
        self.url += f"{self.draft.pk}/"
        for position in (1, 2):
            DraftOrderLine.objects.create(
                organization=self.organization,
                order=self.draft,
                position=position,
                requested_description=f"Synthetic requested line {position}",
            )

    def edit(self, data):
        return self.client.patch(
            self.url,
            data,
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf_token,
        )

    def state(self):
        return DraftOrder.objects.values().get(pk=self.draft.pk)

    def line_state(self):
        return list(DraftOrderLine.objects.order_by("id").values())

    def assert_clean(self):
        self.assertFalse(connection.in_atomic_block)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT NULLIF(current_setting('orderdesk.organization_id', true), ''),"
                " NULLIF(current_setting('orderdesk.user_id', true), '')"
            )
            self.assertEqual(cursor.fetchone(), (None, None))

    def test_active_admin_and_reviewer_edit_with_read_shape_and_timestamp(self):
        lines = self.line_state()
        for role in (MembershipRole.ADMIN, MembershipRole.REVIEWER):
            with self.subTest(role=role):
                self.membership.role = role
                self.membership.save(update_fields=["role"])
                before = self.state()
                read = self.client.get(self.url).json()
                later = before["updated_at"] + timedelta(seconds=10)
                values = {
                    "customer_name": f" {role} customer ",
                    "customer_reference": f"{role}-42",
                }
                with patch("django.utils.timezone.now", return_value=later):
                    response = self.edit(values)
                self.assertEqual(response.status_code, 200, response.content)
                body = response.json()
                self.assertEqual(set(body), set(read))
                self.assertEqual(body["line_count"], 2)
                self.assertEqual(body["lines_url"], read["lines_url"])
                after = self.state()
                for field, value in values.items():
                    self.assertEqual(body[field], value)
                    self.assertEqual(after[field], value)
                self.assertEqual(after["updated_at"], later)
                for field in before.keys() - {*values, "updated_at"}:
                    self.assertEqual(after[field], before[field], field)
                self.assertEqual(self.line_state(), lines)
                self.assert_clean()

    def test_partial_updates_preserve_omitted_field(self):
        for field, value in (
            ("customer_name", "Changed name"),
            ("customer_reference", "Changed reference"),
        ):
            with self.subTest(field=field):
                before = self.state()
                response = self.edit({field: value})
                self.assertEqual(response.status_code, 200, response.content)
                after = self.state()
                self.assertEqual(after[field], value)
                other = (
                    "customer_reference"
                    if field == "customer_name"
                    else "customer_name"
                )
                self.assertEqual(after[other], before[other])

    def test_empty_strings_persist_as_empty_strings(self):
        for field in ("customer_name", "customer_reference"):
            with self.subTest(field=field):
                response = self.edit({field: ""})
                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(response.json()[field], "")
                self.assertEqual(self.state()[field], "")

    def test_whitespace_returns_field_errors_without_save(self):
        before, lines = self.state(), self.line_state()
        for field in ("customer_name", "customer_reference"):
            for value in ("   ", "\t\r\n", "\u2003"):
                with self.subTest(field=field, value=value):
                    with patch.object(DraftOrder, "save") as save:
                        response = self.edit({field: value})
                    self.assertEqual(response.status_code, 400, response.content)
                    self.assertEqual(
                        response.json(),
                        {field: ["Provide a nonblank value or an empty string."]},
                    )
                    save.assert_not_called()
                    self.assertEqual(self.state(), before)
                    self.assertEqual(self.line_state(), lines)

    def test_unknown_immutable_wrong_types_lengths_and_empty_input_do_not_save(self):
        before, lines = self.state(), self.line_state()
        invalid = [
            {},
            [],
            "text",
            {"customer_name": "x" * 256},
            {"customer_reference": "x" * 129},
            *(
                {field: value}
                for field in ("customer_name", "customer_reference")
                for value in (None, True, 12, 1.5, [], {})
            ),
            *(
                {field: value}
                for field, value in {
                    "unknown": True,
                    "original_intake_text": "Replace intake",
                    "organization": str(self.organization.pk),
                    "organization_id": str(self.organization.pk),
                    "initiating_user": str(self.user.pk),
                    "initiating_user_id": str(self.user.pk),
                    "status": "draft",
                    "source_type": "manual",
                    "id": str(self.draft.pk),
                    "created_at": "2026-01-01",
                    "updated_at": "2026-01-01",
                }.items()
            ),
        ]
        for body in invalid:
            with self.subTest(body=body):
                with patch.object(DraftOrder, "save") as save:
                    response = self.edit(body)
                self.assertEqual(response.status_code, 400, response.content)
                save.assert_not_called()
                self.assertEqual(self.state(), before)
                self.assertEqual(self.line_state(), lines)
        with patch.object(DraftOrder, "save") as save:
            response = self.client.patch(
                self.url,
                b"",
                content_type="application/json",
                HTTP_X_CSRFTOKEN=self.csrf_token,
            )
        self.assertEqual(response.status_code, 400)
        save.assert_not_called()

    def test_model_validation_errors_are_stable_400_and_rolled_back(self):
        before, lines = self.state(), self.line_state()
        cases = (
            (
                ValidationError({"customer_name": ["Invalid customer."]}),
                {"customer_name": ["Invalid customer."]},
            ),
            (
                ValidationError({"__all__": ["Invalid draft constraint."]}),
                {"non_field_errors": ["Invalid draft constraint."]},
            ),
            (
                ValidationError(["Invalid draft."]),
                {"non_field_errors": ["Invalid draft."]},
            ),
        )
        original_save = DraftOrder.save
        for error, expected in cases:
            for stage in ("full_clean", "save"):
                with self.subTest(expected=expected, stage=stage):
                    if stage == "full_clean":
                        with (
                            patch.object(DraftOrder, "full_clean", side_effect=error),
                            patch.object(DraftOrder, "save") as save,
                        ):
                            response = self.edit({"customer_name": "Changed"})
                        save.assert_not_called()
                    else:

                        def save_then_fail(
                            order, *args, validation_error=error, **kwargs
                        ):
                            original_save(order, *args, **kwargs)
                            raise validation_error

                        with patch.object(DraftOrder, "save", new=save_then_fail):
                            response = self.edit({"customer_name": "Changed"})
                    self.assertEqual(response.status_code, 400, response.content)
                    self.assertEqual(response.json(), expected)
                    self.assertEqual(self.state(), before)
                    self.assertEqual(self.line_state(), lines)
                    self.assert_clean()

    def test_post_save_materialization_failure_rolls_back(self):
        before = self.state()
        with patch(
            "apps.orders.views.DraftOrderDetailSerializer",
            side_effect=ValidationError({"__all__": ["Invalid materialization."]}),
        ):
            response = self.edit({"customer_reference": "Changed"})
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(
            response.json(), {"non_field_errors": ["Invalid materialization."]}
        )
        self.assertEqual(self.state(), before)
        self.assert_clean()

    def test_authorization_variants_are_403_without_save(self):
        before, lines = self.state(), self.line_state()
        outsider = User.objects.create_superuser(
            email="draft-outsider@example.test", password="synthetic-draft-outsider-42"
        )
        session = self.client.session
        session[SELECTED_WORKSPACE_KEY] = str(self.organization.pk)
        session.save()
        for case in (
            "viewer",
            "inactive_membership",
            "removed",
            "superuser",
            "inactive_user",
            "inactive_workspace",
        ):
            with self.subTest(case=case):
                User.objects.filter(pk=self.user.pk).update(is_active=True)
                type(self.organization).objects.filter(pk=self.organization.pk).update(
                    is_active=True
                )
                self.membership, _ = Membership.objects.update_or_create(
                    user=self.user,
                    organization=self.organization,
                    defaults={"is_active": True, "role": MembershipRole.ADMIN},
                )
                self.client.force_login(self.user)
                if case == "viewer":
                    Membership.objects.filter(pk=self.membership.pk).update(
                        role=MembershipRole.VIEWER
                    )
                elif case == "inactive_membership":
                    Membership.objects.filter(pk=self.membership.pk).update(
                        is_active=False
                    )
                elif case == "removed":
                    self.membership.delete()
                elif case == "superuser":
                    self.client.force_login(outsider)
                elif case == "inactive_user":
                    User.objects.filter(pk=self.user.pk).update(is_active=False)
                else:
                    type(self.organization).objects.filter(
                        pk=self.organization.pk
                    ).update(is_active=False)
                with patch.object(DraftOrder, "save") as save:
                    response = self.edit({"customer_name": "Denied"})
                self.assertEqual(response.status_code, 403, response.content)
                save.assert_not_called()
                self.assertEqual(self.state(), before)
                self.assertEqual(self.line_state(), lines)
                self.assert_clean()

    def test_tenant_scope_rechecks_revocation_after_initial_permission(self):
        before = self.state()

        def revoke_after_permission(**kwargs):
            context = resolve_workspace_context(**kwargs)
            Membership.objects.filter(pk=self.membership.pk).update(is_active=False)
            return context

        with (
            patch(
                "apps.organizations.permissions.resolve_workspace_context",
                side_effect=revoke_after_permission,
            ),
            patch.object(DraftOrder, "save") as save,
        ):
            response = self.edit({"customer_name": "Denied"})
        self.assertEqual(response.status_code, 403, response.content)
        save.assert_not_called()
        self.assertEqual(self.state(), before)
        self.assert_clean()

    def test_foreign_missing_and_malformed_ids_return_404_without_save(self):
        owner = User.objects.create_user(email="other-draft-owner@example.test")
        other = create_organization(actor=owner, name="Other Workspace")
        foreign = DraftOrder.objects.create(
            organization=other,
            initiating_user=owner,
            customer_name="Private synthetic customer",
        )
        before, lines = self.state(), self.line_state()
        not_found = []
        for draft_id in (foreign.pk, uuid4(), "not-a-uuid"):
            with self.subTest(draft_id=draft_id):
                with patch.object(DraftOrder, "save") as save:
                    response = self.client.patch(
                        f"{self.collection_url}{draft_id}/",
                        {"customer_name": "Changed"},
                        format="json",
                        HTTP_X_CSRFTOKEN=self.csrf_token,
                    )
                if draft_id != "not-a-uuid":
                    not_found.append(response.json())
                self.assertEqual(response.status_code, 404, response.content)
                self.assertNotIn("Private synthetic", response.content.decode())
                save.assert_not_called()
        self.assertEqual(not_found[0], not_found[1])
        self.assertEqual(self.state(), before)
        self.assertEqual(self.line_state(), lines)
        foreign.refresh_from_db()
        self.assertEqual(foreign.customer_name, "Private synthetic customer")

    def test_csrf_and_unauthenticated_requests_denied_without_save(self):
        before = self.state()
        for token in (None, "invalid"):
            with self.subTest(token=token):
                kwargs = {} if token is None else {"HTTP_X_CSRFTOKEN": token}
                with patch.object(DraftOrder, "save") as save:
                    response = self.client.patch(
                        self.url, {"customer_name": "Denied"}, format="json", **kwargs
                    )
                self.assertEqual(response.status_code, 403)
                save.assert_not_called()
        self.client.logout()
        with patch.object(DraftOrder, "save") as save:
            response = self.edit({"customer_name": "Denied"})
        self.assertEqual(response.status_code, 403)
        save.assert_not_called()
        self.assertEqual(self.state(), before)

    def test_detail_methods_remain_405_and_edit_never_mutates_lines(self):
        before, lines = self.state(), self.line_state()
        for method in ("put", "delete", "post"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    self.url, {}, format="json", HTTP_X_CSRFTOKEN=self.csrf_token
                )
                self.assertEqual(response.status_code, 405)
        self.assertEqual(self.state(), before)
        line_id = DraftOrderLine.objects.filter(order=self.draft).first().pk
        response = self.client.post(
            f"{self.url}lines/{line_id}/",
            {},
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf_token,
        )
        self.assertEqual(response.status_code, 405)
        response = self.edit({"customer_name": "Changed"})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.line_state(), lines)

    def test_query_media_and_noop_timestamp(self):
        before = self.state()
        for path, body, media in (
            (
                self.url + "?unknown=1",
                '{"customer_name":"Changed"}',
                "application/json",
            ),
            (self.url, "customer_name=Changed", "application/x-www-form-urlencoded"),
        ):
            with self.subTest(path=path, media=media):
                with patch.object(DraftOrder, "save") as save:
                    response = self.client.patch(
                        path, body, content_type=media, HTTP_X_CSRFTOKEN=self.csrf_token
                    )
                self.assertEqual(response.status_code, 400 if "?" in path else 415)
                save.assert_not_called()
        with patch.object(DraftOrder, "save") as save:
            response = self.edit({"customer_name": self.draft.customer_name})
        self.assertEqual(response.status_code, 200, response.content)
        save.assert_not_called()
        self.assertEqual(self.state(), before)

    def test_concurrent_complete_and_partial_edits_have_consistent_final_state(self):
        lines = self.line_state()
        variants = (
            (
                {"customer_name": "First", "customer_reference": "FIRST"},
                {"customer_name": "Second", "customer_reference": "SECOND"},
            ),
            ({"customer_name": "Partial"}, {"customer_reference": "PARTIAL"}),
        )
        for values in variants:
            with self.subTest(values=values):
                barrier = Barrier(2, timeout=10)

                def attempt(body, ready=barrier):
                    close_old_connections()
                    try:
                        client = APIClient(enforce_csrf_checks=True)
                        client.force_login(self.user)
                        token = client.get("/api/v1/auth/csrf/").json()["csrf_token"]
                        ready.wait()
                        response = client.patch(
                            self.url, body, format="json", HTTP_X_CSRFTOKEN=token
                        )
                        self.assertEqual(response.status_code, 200, response.content)
                        for field, value in body.items():
                            self.assertEqual(response.json()[field], value)
                        self.assert_clean()
                    finally:
                        connections["default"].close()

                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(attempt, body) for body in values]
                    for future in futures:
                        future.result(timeout=20)
                after = self.state()
                final = (after["customer_name"], after["customer_reference"])
                if len(values[0]) == 2:
                    self.assertIn(final, (("First", "FIRST"), ("Second", "SECOND")))
                else:
                    self.assertEqual(final, ("Partial", "PARTIAL"))
                self.assertEqual(self.line_state(), lines)
                self.assert_clean()
