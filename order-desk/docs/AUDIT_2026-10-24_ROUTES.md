# Route inventory — 24 October 2026

Resolver inventory for the audited candidate; role/service checks are described
in AUDIT_2026-10-24.md. A class permission list does not replace mutation-specific
role checks in views/services. UUID placeholders are route declarations, not data.
OPTIONS advertises allowed methods; CSRF still applies to unsafe session calls.
Built-in admin methods are delegated to Django; no exhaustive method probing of
every operator form was performed. Root shell is explicitly GET/HEAD only.

| Route | Methods | View | Declared permissions |
| --- | --- | --- | --- |
| `/` | GET, HEAD | `apps.web.views.workspace` | public; require_safe, never_cache |
| `/admin/` | Django admin dispatch | `django.contrib.admin.sites.index` | global staff/admin model permission; login form public |
| `/admin/login/` | Django admin dispatch | `django.contrib.admin.sites.login` | global staff/admin model permission; login form public |
| `/admin/logout/` | Django admin dispatch | `django.contrib.admin.sites.logout` | global staff/admin model permission; login form public |
| `/admin/password_change/` | Django admin dispatch | `django.contrib.admin.sites.password_change` | global staff/admin model permission; login form public |
| `/admin/password_change/done/` | Django admin dispatch | `django.contrib.admin.sites.password_change_done` | global staff/admin model permission; login form public |
| `/admin/autocomplete/` | Django admin dispatch | `django.contrib.admin.sites.autocomplete_view` | global staff/admin model permission; login form public |
| `/admin/jsi18n/` | Django admin dispatch | `django.contrib.admin.sites.i18n_javascript` | global staff/admin model permission; login form public |
| `/admin/r/<path:content_type_id>/<path:object_id>/` | Django admin dispatch | `django.contrib.contenttypes.views.shortcut` | global staff/admin model permission; login form public |
| `/admin/auth/group/` | Django admin dispatch | `django.contrib.admin.options.changelist_view` | global staff/admin model permission; login form public |
| `/admin/auth/group/add/` | Django admin dispatch | `django.contrib.admin.options.add_view` | global staff/admin model permission; login form public |
| `/admin/auth/group/<path:object_id>/history/` | Django admin dispatch | `django.contrib.admin.options.history_view` | global staff/admin model permission; login form public |
| `/admin/auth/group/<path:object_id>/delete/` | Django admin dispatch | `django.contrib.admin.options.delete_view` | global staff/admin model permission; login form public |
| `/admin/auth/group/<path:object_id>/change/` | Django admin dispatch | `django.contrib.admin.options.change_view` | global staff/admin model permission; login form public |
| `/admin/auth/group/<path:object_id>/` | Django admin dispatch | `django.views.generic.base.RedirectView` | global staff/admin model permission; login form public |
| `/admin/accounts/user/<id>/password/` | Django admin dispatch | `django.contrib.auth.admin.user_change_password` | global staff/admin model permission; login form public |
| `/admin/accounts/user/` | Django admin dispatch | `django.contrib.admin.options.changelist_view` | global staff/admin model permission; login form public |
| `/admin/accounts/user/add/` | Django admin dispatch | `django.contrib.auth.admin.add_view` | global staff/admin model permission; login form public |
| `/admin/accounts/user/<path:object_id>/history/` | Django admin dispatch | `django.contrib.admin.options.history_view` | global staff/admin model permission; login form public |
| `/admin/accounts/user/<path:object_id>/delete/` | Django admin dispatch | `django.contrib.admin.options.delete_view` | global staff/admin model permission; login form public |
| `/admin/accounts/user/<path:object_id>/change/` | Django admin dispatch | `django.contrib.admin.options.change_view` | global staff/admin model permission; login form public |
| `/admin/accounts/user/<path:object_id>/` | Django admin dispatch | `django.views.generic.base.RedirectView` | global staff/admin model permission; login form public |
| `/admin/^(?P<app_label>auth|accounts)/$` | Django admin dispatch | `django.contrib.admin.sites.app_index` | global staff/admin model permission; login form public |
| `/admin/(?P<url>.*)$` | Django admin dispatch | `django.contrib.admin.sites.catch_all_view` | global staff/admin model permission; login form public |
| `/api/v1/health/live/` | GET, HEAD, OPTIONS | `apps.health.views.LivenessView` | AllowAny |
| `/api/v1/health/ready/` | GET, HEAD, OPTIONS | `apps.health.views.ReadinessView` | AllowAny |
| `/api/v1/workspaces/` | GET, HEAD, OPTIONS | `apps.organizations.views.WorkspaceListView` | IsAuthenticated |
| `/api/v1/workspaces/current/` | GET, HEAD, PUT, DELETE, OPTIONS | `apps.organizations.views.CurrentWorkspaceView` | IsAuthenticated |
| `/api/v1/workspaces/<uuid:workspace_id>/catalog/imports/dry-run/` | POST, OPTIONS | `apps.catalog.views.CatalogImportDryRunView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/catalog/imports/` | POST, OPTIONS | `apps.catalog.views.CatalogImportExecuteView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/catalog/items/` | GET, HEAD, POST, OPTIONS | `apps.catalog.views.CatalogItemListView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/catalog/items/by-sku/` | GET, HEAD, OPTIONS | `apps.catalog.views.CatalogItemBySKUView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/catalog/items/<uuid:item_id>/` | PATCH, OPTIONS | `apps.catalog.views.CatalogItemUpdateView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/orders/queue/` | GET, HEAD, OPTIONS | `apps.orders.views.OrderQueueView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/orders/<uuid:order_id>/exports/` | GET, HEAD, POST, OPTIONS | `apps.orders.views.OrderExportView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/orders/<uuid:order_id>/exports/<uuid:artifact_id>/download/` | GET, HEAD, OPTIONS | `apps.orders.views.OrderExportDownloadView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/orders/<uuid:order_id>/documents/<uuid:document_id>/extraction/review/` | GET, HEAD, OPTIONS | `apps.orders.views.DocumentExtractionReviewView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/orders/<uuid:order_id>/documents/<uuid:document_id>/extraction/apply/` | POST, OPTIONS | `apps.orders.views.DocumentExtractionApplyView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/orders/<uuid:order_id>/documents/<uuid:document_id>/extraction/` | GET, POST, HEAD, OPTIONS | `apps.orders.views.DocumentExtractionView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/orders/<uuid:order_id>/documents/<uuid:document_id>/extraction/retry/` | POST, OPTIONS | `apps.orders.views.DocumentExtractionRetryView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/orders/<uuid:order_id>/documents/intake/` | GET, POST, HEAD, OPTIONS | `apps.orders.views.PrivateOrderDocumentIntakeView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/orders/<uuid:order_id>/documents/<uuid:document_id>/download/` | GET, HEAD, OPTIONS | `apps.orders.views.OrderDocumentDownloadView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/orders/` | GET, POST, HEAD, OPTIONS | `apps.orders.views.OrderListCreateView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/orders/<uuid:order_id>/` | GET, HEAD, OPTIONS | `apps.orders.views.OrderDetailView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/orders/<uuid:order_id>/lines/` | POST, OPTIONS | `apps.orders.views.OrderLineCreateView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/orders/<uuid:order_id>/documents/` | GET, POST, HEAD, OPTIONS | `apps.orders.views.OrderDocumentListCreateView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/orders/<uuid:order_id>/documents/<uuid:document_id>/reviews/` | GET, POST, HEAD, OPTIONS | `apps.orders.views.OrderDocumentReviewListCreateView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/orders/<uuid:order_id>/documents/<uuid:document_id>/reviews/<uuid:review_id>/resolve/` | POST, OPTIONS | `apps.orders.views.OrderDocumentReviewResolveView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/orders/<uuid:order_id>/submit/` | POST, OPTIONS | `apps.orders.views.OrderReviewActionView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/orders/<uuid:order_id>/approve/` | POST, OPTIONS | `apps.orders.views.OrderReviewActionView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/orders/<uuid:order_id>/reject/` | POST, OPTIONS | `apps.orders.views.OrderReviewActionView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/draft-orders/<uuid:order_id>/suggestions/` | GET, HEAD, OPTIONS | `apps.orders.views.DraftOrderSuggestionsView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/draft-orders/<uuid:order_id>/lines/<uuid:line_id>/accept-suggestion/` | POST, OPTIONS | `apps.orders.views.DraftOrderSuggestionAcceptanceView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/draft-orders/` | GET, HEAD, POST, OPTIONS | `apps.orders.views.DraftOrderListCreateView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/draft-orders/<uuid:order_id>/` | GET, HEAD, PATCH, OPTIONS | `apps.orders.views.DraftOrderDetailView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/draft-orders/<uuid:order_id>/convert/` | POST, OPTIONS | `apps.orders.views.DraftOrderConversionView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/draft-orders/<uuid:order_id>/review/` | GET, HEAD, OPTIONS | `apps.orders.views.DraftOrderReviewView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/draft-orders/<uuid:order_id>/revision/` | GET, HEAD, OPTIONS | `apps.orders.views.DraftOrderRevisionView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/draft-orders/<uuid:order_id>/readiness/` | GET, HEAD, OPTIONS | `apps.orders.views.DraftOrderReadinessView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/draft-orders/<uuid:order_id>/lines/` | GET, HEAD, POST, OPTIONS | `apps.orders.views.DraftOrderLinesView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/draft-orders/<uuid:order_id>/lines/<uuid:line_id>/` | GET, HEAD, PATCH, OPTIONS | `apps.orders.views.DraftOrderLineDetailView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/draft-orders/<uuid:order_id>/lines/<uuid:line_id>/attach/` | POST, OPTIONS | `apps.orders.views.DraftOrderLineAttachmentView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/draft-orders/<uuid:order_id>/lines/<uuid:line_id>/detach/` | POST, OPTIONS | `apps.orders.views.DraftOrderLineDetachmentView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/workspaces/<uuid:workspace_id>/context/` | GET, HEAD, OPTIONS | `apps.organizations.views.WorkspaceContextView` | IsAuthenticated, HasWorkspaceAccess |
| `/api/v1/auth/csrf/` | GET, HEAD, OPTIONS | `apps.accounts.views.CsrfTokenView` | AllowAny |
| `/api/v1/auth/login/` | POST, OPTIONS | `apps.accounts.views.SessionLoginView` | AllowAny |
| `/api/v1/auth/logout/` | POST, OPTIONS | `apps.accounts.views.SessionLogoutView` | AllowAny |
