from django.urls import path

from api.views import dev_users, health, whoami

urlpatterns = [
    path("health/", health, name="health"),
    path("auth/whoami/", whoami, name="whoami"),
    path("auth/dev-users/", dev_users, name="dev_users"),
]
