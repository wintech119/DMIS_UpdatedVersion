# Lessons

- When CodeRabbit skips a lockfile-only PR due to default path filters, verify the repo-tracked `.coderabbit.yaml`; an ignored local config will not affect remote reviews.
- When adding CodeRabbit positive path filters to override a default block, include the broader repository review scope as well; a single positive pattern can narrow future reviews too far.

- When a review pass mixes backend control gaps with a frontend no-visual constraint, verify the live tree first and keep frontend fixes to behavior, validation, accessibility, and lint-safe syntax unless the user explicitly authorizes visual changes.

- For repo-local MCP repairs, keep a single canonical MCP alias per launcher, align the MCP-only requirements pin with the installed backend venv, and validate both TOML parsing and a short launcher startup smoke before closing the task.

- When a dashboard preset or search label changes, verify the underlying sort/filter contract directly and add regression tests that prove the label matches the behavior users see.
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
- When a list endpoint still needs one Python-only filter, keep the common case on DB-side count/slice/order and fall back to bounded batch scanning for the edge filter instead of materializing the full header set in memory.
- When adding pagination to an existing API list surface, keep the stable collection key if possible and add explicit count/next/previous metadata so current consumers can stay compatible while the response becomes bounded.
- Ensure idempotent Django write paths satisfy both sides of the retry contract: cached replays must bypass throttles where intended, and success responses must only be written to cache in `transaction.on_commit(...)` so rollback paths cannot publish false success.
- Scope the cache key by actor plus tenant/resource in multi-tenant Django write paths, and reserve the key before the write path so concurrent retries cannot bypass access checks or race each other past the first cache miss.
- If an idempotency helper already requires a header semantically, keep its public signature non-optional and mock replay helpers explicitly in rate-limit tests so the test stays deterministic instead of depending on live cache behavior.
- Pair the success-side `transaction.on_commit(...)` cache publication with an exception-path release outside the atomic boundary whenever an idempotent Django write path reserves a cache lease before mutating state, so failed writes do not strand the in-progress marker until TTL expiry.
- When Django operations endpoints require `Idempotency-Key`, mirror that contract in the shared Angular service layer and add focused service specs per mutating endpoint so workflow buttons do not rediscover the gap screen by screen.
- When a backend read path already grants `SYSTEM_ADMINISTRATOR` a cross-tenant workflow bypass, keep the paired write-scope helper aligned as well; otherwise the UI can load a record and then fail its submit action with a masked 404 that looks like missing data.
- When allocation UI caps quantities, base card-level clamps on residual `remaining_qty` and only add back the active card's own reservation; using original `request_qty` reopens quantities already issued on other package legs.
- When allocation commits accept submitted source/destination warehouses, validate every warehouse against the caller's tenant write scope before override detection or commit helpers run; route permission alone is not enough for stock movement.
- When backend contract tests assert validation order after tenant-scope enforcement, create the current operations request record explicitly; do not rely on incidental legacy agency scope or retained `--keepdb` rows to satisfy access preconditions.
- When local-harness queue visibility depends on an ODPEM tenant-scoped workflow lane, drive the harness personas from the same explicit `ODPEM_TENANT_ID` setting that the backend routing code uses; do not let test-user seeding and workflow assignment each guess a different “national” tenant.
