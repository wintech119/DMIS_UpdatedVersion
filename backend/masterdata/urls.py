from django.urls import path

from masterdata import views

urlpatterns = [
    # IFRC assistant endpoints (must come before generic table routes)
    path("items/ifrc-suggest", views.ifrc_suggest, name="ifrc-suggest"),
    path("items/ifrc-health", views.ifrc_health, name="ifrc-health"),

    # Generic CRUD endpoints parameterized by table_key
    path("<str:table_key>/", views.master_list_create, name="master-list-create"),
    path("<str:table_key>/summary", views.master_summary, name="master-summary"),
    path("<str:table_key>/lookup", views.master_lookup, name="master-lookup"),
    path("<str:table_key>/<str:pk>", views.master_detail_update, name="master-detail-update"),
    path("<str:table_key>/<str:pk>/inactivate", views.master_inactivate, name="master-inactivate"),
    path("<str:table_key>/<str:pk>/activate", views.master_activate, name="master-activate"),
]
