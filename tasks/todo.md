# Current Task Plan

1. Verify the current idempotency helper and each affected write path in `backend/operations/contract_services.py`, then add a shared reservation/replay helper only where the race still exists.
2. Add the missing tenant-scoped idempotency regression in `backend/operations/tests_contract_services.py` and keep the existing post-commit cache assertions intact.
3. Fix the verified parser and import-error handling issues in `backend/run_mcp.py` without changing unrelated launcher behavior.
4. Run targeted backend tests and lightweight script verification, then finish with backend and architecture review conclusions.
