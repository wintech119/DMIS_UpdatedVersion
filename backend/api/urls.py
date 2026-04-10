from django.urls import path

from api.views import health, health_live, health_ready, local_auth_harness, whoami

urlpatterns = [
    path("health/", health, name="health"),
    path("health/live/", health_live, name="health_live"),
    path("health/ready/", health_ready, name="health_ready"),
    path("auth/whoami/", whoami, name="whoami"),
    path("auth/local-harness/", local_auth_harness, name="local_auth_harness"),
]
