# Current Task Plan

1. Completed: verified the rollback-lease and legacy-dispatch idempotency findings against the current `contract_services.py` implementation and existing tests.
2. Completed: released idempotency reservations on failed write paths and moved dispatch reservation ahead of the legacy/scoped branch split.
3. Completed: added focused contract-service regressions for rollback/failure reservation release and legacy dispatch idempotent replay.
4. Completed: ran targeted backend tests and finished the backend and architecture review pass.
