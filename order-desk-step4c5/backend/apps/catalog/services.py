"""Catalogue creation with fresh administrator checks and an owned write scope."""

from collections.abc import Callable
from typing import TYPE_CHECKING
from uuid import UUID

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, IntegrityError

from apps.catalog.models import CatalogItem
from apps.catalog.serializers import CatalogItemCreateSerializer
from apps.organizations.models import MembershipRole
from apps.organizations.transactions import tenant_scope

if TYPE_CHECKING:
    from apps.accounts.models import User


CATALOG_CREATE_DENIED = (
    "You do not have permission to create catalogue items in this workspace."
)
CATALOG_SKU_CONFLICT = "A catalogue item with this stock code already exists."


class CatalogSKUConflict(Exception):
    """The database rejected a stock code already present in this workspace."""

    def __init__(self) -> None:
        super().__init__(CATALOG_SKU_CONFLICT)


def create_catalog_item[Result](
    *,
    actor: User | AnonymousUser,
    organization_id: UUID,
    data: object | Callable[[], object],
    materialize: Callable[[CatalogItem], Result] | None = None,
) -> CatalogItem | Result:
    """Authorize, validate, insert, and materialize inside an owned write scope.

    A server-supplied data callback defers parsing until fresh admin authorization.
    Related/deferred database work must not escape through the returned value.
    The caller must not wrap this service in another transaction or tenant scope.
    """
    try:
        with tenant_scope(
            user=actor, workspace_id=organization_id, write=True
        ) as scope:
            if scope.role != MembershipRole.ADMIN:
                raise PermissionDenied(CATALOG_CREATE_DENIED)
            serializer = CatalogItemCreateSerializer(
                data=data() if callable(data) else data
            )
            serializer.is_valid(raise_exception=True)
            item = CatalogItem(
                organization_id=scope.organization_id,
                **serializer.validated_data,
            )
            # Field/model validation stays enabled. The database alone arbitrates
            # uniqueness, including concurrent requests, using its named constraint.
            item.full_clean(validate_unique=False, validate_constraints=False)
            item.save()
            return materialize(item) if materialize is not None else item
    except DatabaseError as error:
        # Translate only known catalogue failures after the scope has rolled back.
        cause = error.__cause__
        diagnostics = getattr(cause, "diag", None)
        constraint_name = getattr(diagnostics, "constraint_name", None)
        if (
            isinstance(error, IntegrityError)
            and getattr(cause, "sqlstate", None) == "23505"
            and constraint_name == "catalog_org_sku_unique"
        ):
            raise CatalogSKUConflict from error
        if (
            getattr(cause, "sqlstate", None) == "54000"
            and constraint_name == "catalog_org_sku_unique"
            and getattr(diagnostics, "table_name", None) == "catalog_catalogitem"
        ):
            raise ValidationError(
                {"sku": ["This stock code is too large for the catalogue index."]}
            ) from error
        raise
