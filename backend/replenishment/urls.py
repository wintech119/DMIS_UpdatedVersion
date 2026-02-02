from django.urls import path

from replenishment.views import (
    needs_list_approve,
    needs_list_cancel,
    needs_list_draft,
    needs_list_edit_lines,
    needs_list_escalate,
    needs_list_get,
    needs_list_mark_completed,
    needs_list_mark_dispatched,
    needs_list_mark_received,
    needs_list_preview,
    needs_list_reject,
    needs_list_return,
    needs_list_review_start,
    needs_list_start_preparation,
    needs_list_submit,
)

urlpatterns = [
    path("needs-list/preview", needs_list_preview, name="needs_list_preview"),
    path("needs-list/draft", needs_list_draft, name="needs_list_draft"),
    path("needs-list/<str:needs_list_id>", needs_list_get, name="needs_list_get"),
    path(
        "needs-list/<str:needs_list_id>/lines",
        needs_list_edit_lines,
        name="needs_list_edit_lines",
    ),
    path(
        "needs-list/<str:needs_list_id>/submit",
        needs_list_submit,
        name="needs_list_submit",
    ),
    path(
        "needs-list/<str:needs_list_id>/review/start",
        needs_list_review_start,
        name="needs_list_review_start",
    ),
    path(
        "needs-list/<str:needs_list_id>/return",
        needs_list_return,
        name="needs_list_return",
    ),
    path(
        "needs-list/<str:needs_list_id>/reject",
        needs_list_reject,
        name="needs_list_reject",
    ),
    path(
        "needs-list/<str:needs_list_id>/approve",
        needs_list_approve,
        name="needs_list_approve",
    ),
    path(
        "needs-list/<str:needs_list_id>/escalate",
        needs_list_escalate,
        name="needs_list_escalate",
    ),
    path(
        "needs-list/<str:needs_list_id>/start-preparation",
        needs_list_start_preparation,
        name="needs_list_start_preparation",
    ),
    path(
        "needs-list/<str:needs_list_id>/mark-dispatched",
        needs_list_mark_dispatched,
        name="needs_list_mark_dispatched",
    ),
    path(
        "needs-list/<str:needs_list_id>/mark-received",
        needs_list_mark_received,
        name="needs_list_mark_received",
    ),
    path(
        "needs-list/<str:needs_list_id>/mark-completed",
        needs_list_mark_completed,
        name="needs_list_mark_completed",
    ),
    path(
        "needs-list/<str:needs_list_id>/cancel",
        needs_list_cancel,
        name="needs_list_cancel",
    ),
]
