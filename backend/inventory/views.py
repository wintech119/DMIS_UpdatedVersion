"""
DRF views for the inventory module. Sprint 1 ships the read-side and the
Opening Balance workflow end-to-end. Stub view functions exist for the
scaffolded workflows and will be filled in by later sprints.
"""

from __future__ import annotations

from rest_framework.decorators import api_view
from rest_framework.response import Response


@api_view(["GET"])
def inventory_health(request):
    """Lightweight health endpoint for the inventory module."""
    return Response({"status": "ok", "module": "inventory"})
