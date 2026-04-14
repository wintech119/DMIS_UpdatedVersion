# Lessons

- When a review comment flags sensitive identifiers stored in both columns and JSON artifacts, fix both storage paths together and add a data migration so old rows do not keep the plaintext value.
- For staged dispatch flows, keep dispatch persistence aligned with `effective_dispatch_source_warehouse_id` rather than assuming `source_warehouse_id` is already normalized.
- When review comments reference moved or already-fixed code, verify the live call site first, then patch the real implementation and add transaction or request-ordering tests so stale responses and half-applied repairs cannot slip through.
- When tightening allocation or access-control behavior, update the regression tests to assert the new contract directly instead of preserving stale expectations that hide the verified fix.
- When a UI classification helper and its stage-mapping helper disagree, align both against the current data contract and add tests around legacy fallback fields instead of assuming only the newest nested object shape is present.
- When a security review comment references sensitive data persistence, verify the live model, write path, and migrations together before adding new crypto or backfills; stale comments can describe a risk the current tree already removed.
- When review comments point at sensitive-data or contract issues, verify the live model and write path first; stale comments often mean the real work is in the remaining adapters, labels, or fallback paths rather than a full rewrite.
- When workflow storage supports both legacy file hooks and DB-backed paths, guard optional helpers like `_store_path` in tests and add narrow endpoint contract tests for public status normalization instead of relying only on longer workflow happy-path coverage.
- When optimizing hot Django list endpoints, keep summary surfaces summary-only by default, batch shared lookups, and add tests that prove expensive per-row hydration stays opt-in rather than silently returning.
- When a paginated Django summary endpoint still needs item-derived metrics, split cheap header filtering/sorting from page hydration so tenant scope and page windows cut the expensive item load before serialization.
- When adding early tenant-aware prefilters, preserve the existing read-all contract for NEOC/national contexts; requested-tenant state can shape active context without becoming an implicit deny-by-omission filter.
