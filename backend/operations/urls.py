from django.urls import path

from operations.views import (
    operations_dispatch_detail,
    operations_dispatch_handoff,
    operations_dispatch_queue,
    operations_dispatch_waybill,
    operations_eligibility_detail,
    operations_eligibility_decision,
    operations_eligibility_queue,
    operations_package_allocation_options,
    operations_package_commit_allocation,
    operations_package_current,
    operations_package_draft,
    operations_package_override_approve,
    operations_packages_queue,
    operations_request_detail,
    operations_request_submit,
    operations_requests,
)

urlpatterns = [
    path("requests", operations_requests, name="operations_requests"),
    path("requests/<int:reliefrqst_id>", operations_request_detail, name="operations_request_detail"),
    path("requests/<int:reliefrqst_id>/submit", operations_request_submit, name="operations_request_submit"),
    path("eligibility/queue", operations_eligibility_queue, name="operations_eligibility_queue"),
    path("eligibility/<int:reliefrqst_id>", operations_eligibility_detail, name="operations_eligibility_detail"),
    path(
        "eligibility/<int:reliefrqst_id>/decision",
        operations_eligibility_decision,
        name="operations_eligibility_decision",
    ),
    path("packages/queue", operations_packages_queue, name="operations_packages_queue"),
    path("packages/<int:reliefrqst_id>", operations_package_current, name="operations_package_current"),
    path("packages/<int:reliefrqst_id>/draft", operations_package_draft, name="operations_package_draft"),
    path(
        "packages/<int:reliefrqst_id>/allocation-options",
        operations_package_allocation_options,
        name="operations_package_allocation_options",
    ),
    path(
        "packages/<int:reliefrqst_id>/allocations/commit",
        operations_package_commit_allocation,
        name="operations_package_commit_allocation",
    ),
    path(
        "packages/<int:reliefrqst_id>/allocations/override-approve",
        operations_package_override_approve,
        name="operations_package_override_approve",
    ),
    path("dispatch/queue", operations_dispatch_queue, name="operations_dispatch_queue"),
    path("dispatch/<int:reliefpkg_id>", operations_dispatch_detail, name="operations_dispatch_detail"),
    path(
        "dispatch/<int:reliefpkg_id>/handoff",
        operations_dispatch_handoff,
        name="operations_dispatch_handoff",
    ),
    path(
        "dispatch/<int:reliefpkg_id>/waybill",
        operations_dispatch_waybill,
        name="operations_dispatch_waybill",
    ),
]

