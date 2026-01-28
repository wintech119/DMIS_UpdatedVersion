from django.urls import path

from replenishment.views import needs_list_preview

urlpatterns = [
    path("needs-list/preview", needs_list_preview, name="needs_list_preview"),
]
