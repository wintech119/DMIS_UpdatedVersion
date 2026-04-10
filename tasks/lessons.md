# Lessons

- When a review comment flags sensitive identifiers stored in both columns and JSON artifacts, fix both storage paths together and add a data migration so old rows do not keep the plaintext value.
- For staged dispatch flows, keep dispatch persistence aligned with `effective_dispatch_source_warehouse_id` rather than assuming `source_warehouse_id` is already normalized.
- When review comments reference moved or already-fixed code, verify the live call site first, then patch the real implementation and add transaction or request-ordering tests so stale responses and half-applied repairs cannot slip through.
- When tightening allocation or access-control behavior, update the regression tests to assert the new contract directly instead of preserving stale expectations that hide the verified fix.
