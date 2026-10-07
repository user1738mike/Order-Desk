import django
import secrets
from uuid import uuid4
django.setup()
from django.db import connection, transaction, DatabaseError
from apps.accounts.models import User
from apps.organizations.models import Organization, Membership, MembershipRole
from apps.catalog.models import CatalogItem
from apps.catalog.services import create_catalog_item
actor_id, workspace_id = uuid4(), uuid4()
with connection.cursor() as cursor:
    cursor.execute("SELECT current_database(), current_user, session_user")
    if cursor.fetchone() != ("test_orderdesk", "orderdesk_migrator", "orderdesk_migrator"):
        raise RuntimeError("Index probe is restricted to the dedicated test database.")
try:
    with transaction.atomic():
        actor = User.objects.create_user(id=actor_id, email=f"index-probe-{actor_id.hex}@example.test")
        workspace = Organization.objects.create(id=workspace_id, name="Synthetic index-width probe")
        Membership.objects.create(user=actor, organization=workspace, role=MembershipRole.ADMIN)
    try:
        create_catalog_item(actor=actor, organization_id=workspace_id, data={"sku": secrets.token_urlsafe(3750)})
    except DatabaseError as error:
        cause = error.__cause__
        diag = getattr(cause, "diag", None)
        print({"error_class": type(cause).__name__, "sqlstate": getattr(cause, "sqlstate", None), "constraint": getattr(diag, "constraint_name", None), "table": getattr(diag, "table_name", None), "mentions_catalogue_index": "catalog_org_sku_unique" in (getattr(diag, "message_primary", "") or "")})
    else:
        print("Long incompressible stock code accepted.")
    print({"partial_items": CatalogItem.objects.filter(organization_id=workspace_id).count(), "transaction_open": connection.in_atomic_block})
finally:
    with transaction.atomic():
        CatalogItem.objects.filter(organization_id=workspace_id).delete()
        Membership.objects.filter(organization_id=workspace_id).delete()
        Organization.objects.filter(id=workspace_id).delete()
        User.objects.filter(id=actor_id).delete()

