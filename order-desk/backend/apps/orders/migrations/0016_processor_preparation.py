"""Extend preparation policies only; approval/conversion/reference rights stay put."""

from importlib import import_module

from django.db import migrations

drafts = import_module("apps.orders.migrations.0007_draft_order_boundary")


def policies(processor):
    roles = "'admin', 'reviewer'" + (", 'processor'" if processor else "")
    statements = []
    for table, prefix, insert_extra, update_extra in (
        ("orders_draftorder", "draftorder_writer", drafts.HEADER_INSERT, "true"),
        ("orders_draftorderline", "draftline_writer", drafts.LINE_PARENT, drafts.LINE_PARENT),
        ("orders_orderdocument", "orderdocument_reviewer", "true", "true"),
        ("orders_orderdocumentreview", "orderreview_reviewer", "true", "true"),
        ("orders_documentextractionjob", "extraction_reviewer", "true", "true"),
        ("orders_extractionapplication", "application_reviewer", "true", "true"),
        ("orders_extractioncreatedrow", "createdrow_reviewer", "true", "true"),
        ("customers_draftcustomerdecision", "customer_decision_reviewer", "true", "true"),
    ):
        writer = f"""EXISTS (
            SELECT 1 FROM public.organizations_membership m
            WHERE m.organization_id={table}.organization_id
            AND m.user_id=NULLIF(current_setting('orderdesk.user_id',true),'')::uuid
            AND m.is_active AND m.role IN ({roles}))"""
        statements.append(f"""
            ALTER POLICY {prefix}_insert ON public.{table}
              WITH CHECK ({writer} AND ({insert_extra}));
            ALTER POLICY {prefix}_update ON public.{table}
              USING ({writer} AND ({update_extra}))
              WITH CHECK ({writer} AND ({update_extra}));
        """)
    return "\n".join(statements)


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0015_incoming_document_ownership"),
        ("customers", "0003_reference_write_receipts"),
        ("organizations", "0002_remove_membership_org_membership_role_valid_and_more"),
    ]
    operations = [migrations.RunSQL(policies(True), policies(False))]
