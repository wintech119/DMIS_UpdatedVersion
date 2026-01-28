from django.urls import path

from api.views import health, whoami

urlpatterns = [
    path("health/", health, name="health"),
    path("auth/whoami/", whoami, name="whoami"),
]
