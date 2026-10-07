from django.db import migrations, models
import django.db.models.deletion
import uuid


def _noop(apps, schema_editor):
    return None


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("accounts", "0001_initial"),
        ("organizations", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="PurchaseOrder",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("customer_name", models.CharField(max_length=255, validators=[django.core.validators.RegexValidator("\\S", "Enter a nonblank customer name.")])),
                ("purchase_order_number", models.CharField(max_length=64, validators=[django.core.validators.RegexValidator("\\S", "Enter a nonblank purchase order number.")])),
                ("status", models.CharField(choices=[("draft", "Draft"), ("pending_review", "Pending review"), ("approved", "Approved"), ("rejected", "Rejected")], default="draft", max_length=32)),
                ("is_active", models.BooleanField(default=True)),
                ("source_document", models.CharField(blank=True, default="", max_length=255)),
                ("comments", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="purchase_orders", to="accounts.user")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="purchase_orders", to="organizations.organization")),
            ],
            options={},
        ),
        migrations.AddConstraint(
            model_name="purchaseorder",
            constraint=models.CheckConstraint(condition=models.Q(("customer_name__regex", "\\S")), name="purchaseorder_customer_name_not_blank"),
        ),
        migrations.AddConstraint(
            model_name="purchaseorder",
            constraint=models.CheckConstraint(condition=models.Q(("purchase_order_number__regex", "\\S")), name="purchaseorder_number_not_blank"),
        ),
        migrations.AddConstraint(
            model_name="purchaseorder",
            constraint=models.UniqueConstraint(fields=("organization", "purchase_order_number"), name="purchaseorder_org_number_unique"),
        ),
        migrations.CreateModel(
            name="PurchaseOrderLine",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("line_number", models.PositiveIntegerField()),
                ("sku", models.CharField(max_length=128, validators=[django.core.validators.RegexValidator("\\S", "Enter a nonblank stock code.")])),
                ("description", models.TextField(blank=True, default="")),
                ("quantity", models.DecimalField(decimal_places=4, max_digits=18)),
                ("unit", models.CharField(blank=True, default="", max_length=32)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("order", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="lines", to="orders.purchaseorder")),
            ],
            options={},
        ),
        migrations.AddConstraint(
            model_name="purchaseorderline",
            constraint=models.CheckConstraint(condition=models.Q(("line_number__gt", 0)), name="purchaseorderline_line_number_positive"),
        ),
        migrations.AddConstraint(
            model_name="purchaseorderline",
            constraint=models.CheckConstraint(condition=models.Q(("quantity__gt", 0)), name="purchaseorderline_quantity_positive"),
        ),
        migrations.AddConstraint(
            model_name="purchaseorderline",
            constraint=models.CheckConstraint(condition=models.Q(("sku__regex", "\\S")), name="purchaseorderline_sku_not_blank"),
        ),
        migrations.AddConstraint(
            model_name="purchaseorderline",
            constraint=models.UniqueConstraint(fields=("order", "line_number"), name="purchaseorderline_order_number_unique"),
        ),
    ]
