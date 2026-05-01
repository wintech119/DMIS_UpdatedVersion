"""URL routes for the inventory module. Mounted at /api/v1/inventory/."""

from __future__ import annotations

from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("health/", views.inventory_health, name="inventory-health"),
]
