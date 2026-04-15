# Current Task Plan

1. Verify each requested review comment against the live code and discard the stale ones instead of applying them blindly.
2. Standardize the requirements-to-design skill hook by adding the missing `.agents` skill path and repointing the four instruction docs to the same canonical location.
3. Patch the confirmed backend gaps only where they still exist: procurement exception handling, bounded pagination, tenant-safe procurement reads, real pagination validation errors, `_iso_or_none(None)`, DB-side method-filter pagination, and the raw-SQL warehouse scope helper move.
4. Update the affected replenishment tests so they prove the real behavior: offset handling, tenant-safe non-exposure, procurement scope filtering, and invalid pagination rejection.
5. Run targeted backend tests and finish with a system-architecture review decision against the architecture and security source-of-truth docs.
