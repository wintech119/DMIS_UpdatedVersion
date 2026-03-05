from django.contrib import admin

from masterdata.models import ItemIfrcSuggestLog


@admin.register(ItemIfrcSuggestLog)
class ItemIfrcSuggestLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "item_name_input",
        "suggested_code",
        "match_type",
        "confidence",
        "selected_code",
        "user_id",
    )
    list_filter = ("match_type",)
    search_fields = ("item_name_input", "suggested_code", "selected_code", "user_id")
    readonly_fields = tuple(field.name for field in ItemIfrcSuggestLog._meta.fields)
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
