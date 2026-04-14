# Current Task Plan

1. Re-verify the replenishment and operations review findings against the live code so stale comments are not reimplemented.
2. Patch the confirmed replenishment gaps only where they still exist: guard legacy `_store_path()` calls, add procurement export tenant-negative coverage, and normalize the mark-completed response status.
3. Patch the confirmed operations gaps only where they still exist: hide scope leaks behind generic 404s, add end-to-end idempotency for partial-release request, and make rate-limit lock release owner-safe.
4. Run targeted Django tests for the touched replenishment and operations paths, then capture the final system-architecture-review decision.
