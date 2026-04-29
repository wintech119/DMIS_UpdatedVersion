from django.conf import settings
from django.urls import include, path

urlpatterns = [
    path("api/v1/", include("api.urls")),
    path("api/v1/masterdata/", include("masterdata.urls")),
]
if settings.DMIS_REPLENISHMENT_ENABLED:
    urlpatterns.append(path("api/v1/replenishment/", include("replenishment.urls")))
if settings.DMIS_OPERATIONS_ENABLED:
    urlpatterns.append(path("api/v1/operations/", include("operations.urls")))
