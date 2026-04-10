from django.urls import path

from api.views import dev_users, health, local_auth_harness, whoami

urlpatterns = [
    path("health/", health, name="health"),
    path("auth/whoami/", whoami, name="whoami"),
    path("auth/local-harness/", local_auth_harness, name="local_auth_harness"),
    path("auth/dev-users/", dev_users, name="dev_users"),
]
