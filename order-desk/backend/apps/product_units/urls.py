from django.urls import path

from apps.product_units.views import OperationView, ReferenceListView

urlpatterns = [path("operations/<uuid:operation_key>/", OperationView.as_view())]
for route, kind in (("units", "unit"), ("policies", "policy"), ("aliases", "alias")):
    urlpatterns.extend(
        [
            path(route + "/", ReferenceListView.as_view(kind=kind)),
            path(route + "/<uuid:record_id>/", ReferenceListView.as_view(kind=kind)),
        ]
    )
