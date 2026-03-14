from django.urls import path

from masterdata import views

urlpatterns = [
    # IFRC assistant endpoints (must come before generic table routes)
    path("items/ifrc-suggest", views.ifrc_suggest, name="ifrc-suggest"),
    path("items/ifrc-health", views.ifrc_health, name="ifrc-health"),
    path("items/categories/lookup", views.item_level1_category_lookup, name="item-category-lookup"),
    path("items/ifrc-families/lookup", views.item_ifrc_family_lookup, name="item-ifrc-family-lookup"),
    path("items/ifrc-references/lookup", views.item_ifrc_reference_lookup, name="item-ifrc-reference-lookup"),
    path("ifrc-families/suggest", views.ifrc_family_suggest, name="ifrc-family-suggest"),
    path("ifrc-item-references/suggest", views.ifrc_item_reference_suggest, name="ifrc-item-reference-suggest"),
    path("ifrc-families/<str:pk>/replacement", views.ifrc_family_replacement, name="ifrc-family-replacement"),
    path("ifrc-item-references/<str:pk>/replacement", views.ifrc_item_reference_replacement, name="ifrc-item-reference-replacement"),

    # Generic CRUD endpoints parameterized by table_key
    path("<str:table_key>/", views.master_list_create, name="master-list-create"),
    path("<str:table_key>/summary", views.master_summary, name="master-summary"),
    path("<str:table_key>/lookup", views.master_lookup, name="master-lookup"),
    path("<str:table_key>/<str:pk>", views.master_detail_update, name="master-detail-update"),
    path("<str:table_key>/<str:pk>/inactivate", views.master_inactivate, name="master-inactivate"),
    path("<str:table_key>/<str:pk>/activate", views.master_activate, name="master-activate"),
]
