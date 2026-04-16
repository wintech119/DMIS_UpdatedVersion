# Current Task Plan

1. Replace inline idempotency cache writes with a post-commit helper in `backend/operations/contract_services.py` so success responses are only cached after the transaction commits.
2. Preserve the view-layer fix that lets cached idempotent retries bypass workflow throttling, and extend that ordering consistently across the remaining idempotent workflow handlers in `backend/operations/views.py`.
3. Add contract-service regression tests that prove the submit and eligibility idempotency cache writes are deferred via commit callbacks.
4. Run the targeted operations API and contract-service tests, then finish with a backend review and architecture verdict.
