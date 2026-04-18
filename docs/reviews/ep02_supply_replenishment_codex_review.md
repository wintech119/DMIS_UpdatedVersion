# Codex Review: EP-02 Supply Replenishment Module

## Scope

Product Backlog v3.2 is the authoritative requirements source for EP-02. For this review, the workbook at `C:\Users\wbowe\OneDrive\Desktop\project\DMIS_UpdatedVersion\docs\attached_assets\DMIS_Product_Backlog_v3.2.xlsx` is treated as the source of truth, while the older prose requirements/design docs are treated as supplemental context only.

Review of the EP-02 supply replenishment module across:

- Requirements in `DMIS_Product_Backlog_v3.2.xlsx` (authoritative), with `docs/attached_assets/EP02_SUPPLY_REPLENISHMENT_REQUIREMENTS.md`, `CLAUDE.md`, `DASHBOARD_IMPLEMENTATION_SUMMARY.md`, and `frontend/NEEDS_LIST_WIZARD_IMPLEMENTATION_GUIDE.md` used only as supporting context
- Backend implementation in `backend/replenishment/*`
- Frontend implementation in `frontend/src/app/replenishment/*`
- Alignment with `docs/security/SECURITY_ARCHITECTURE.md`

## Findings

1. **The needs-list workflow is still wired to the dev-only JSON store, not the database-backed store described as production-ready**
   - `backend/replenishment/views.py` imports `workflow_store` directly and every draft/workflow endpoint fails closed unless `workflow_store.store_enabled_or_raise()` passes.
   - The imported store is the JSON file implementation, which only enables when `NEEDS_WORKFLOW_DEV_STORE=1` and persists to `.local/needs_list_store.json`.
   - This means the documented production workflow in `workflow_store_db.py` is not actually on the request path, and the module cannot create or move real needs lists unless the dev store flag is enabled.
   - Key refs: `backend/replenishment/views.py:27`, `backend/replenishment/views.py:482`, `backend/replenishment/views.py:523`, `backend/replenishment/workflow_store.py:18`, `backend/replenishment/workflow_store.py:22`, `backend/replenishment/workflow_store.py:287`

2. **The workflow state machine is inconsistent with the Backlog v3.2 status contract**
   - Backlog v3.2 makes FR02.90-FR02.98 the authoritative needs-list workflow, including statuses `DRAFT`, `MODIFIED`, `SUBMITTED`, `APPROVED`, `REJECTED`, `IN_PROGRESS`, `FULFILLED`, and `SUPERSEDED`.
   - The Django model and Angular types instead use `PENDING_APPROVAL`, `UNDER_REVIEW`, `RETURNED`, and `CANCELLED`, which do not match the backlog vocabulary.
   - The active backend controller path also introduces execution statuses such as `ESCALATED`, `IN_PREPARATION`, `DISPATCHED`, `RECEIVED`, and `COMPLETED`, which are outside the needs-list status model defined in the backlog.
   - As a result, the EP-02 approval workflow cannot be traced cleanly from requirements to schema to API to UI.
   - Key refs: `backend/EP02_SUPPLY_REPLENISHMENT_SCHEMA.sql:195`, `backend/replenishment/models.py:118`, `backend/replenishment/views.py:701`, `backend/replenishment/views.py:781`, `backend/replenishment/views.py:945`, `backend/replenishment/views.py:981`, `backend/replenishment/views.py:1015`, `backend/replenishment/views.py:1049`, `backend/replenishment/views.py:1083`, `frontend/src/app/replenishment/models/needs-list.model.ts:118`, `frontend/src/app/replenishment/shared/dmis-approval-status-tracker/dmis-approval-status-tracker.component.ts:31`

3. **Even if the database-backed store is enabled, it does not match the current preview payload contract**
   - `workflow_store_db.create_draft()` expects flat fields such as `burn_rate`, `coverage_qty`, `severity`, and `horizon_a_qty`.
   - The preview builder returns `burn_rate_per_hour`, nested `horizon` data, lower-level freshness metadata, and no server-side `severity` field.
   - As written, DB drafts would silently lose burn rate, coverage, severity, horizon allocations, and freshness fidelity, which makes the persistence layer unsafe to switch on without a contract pass.
   - Key refs: `backend/replenishment/workflow_store_db.py:137`, `backend/replenishment/workflow_store_db.py:144`, `backend/replenishment/workflow_store_db.py:152`, `backend/replenishment/workflow_store_db.py:155`, `backend/replenishment/workflow_store_db.py:156`, `backend/replenishment/services/needs_list.py:357`, `backend/replenishment/services/needs_list.py:363`, `backend/replenishment/services/needs_list.py:372`, `backend/replenishment/services/needs_list.py:376`

4. **Dashboard freshness handling is broken against the Backlog v3.2 confidence model**
   - FR02.83-FR02.85 require data freshness indicators on dashboards and needs lists using `HIGH`, `MEDIUM`, and `LOW` confidence levels tied to phase-specific freshness thresholds.
   - The backend emits freshness as `fresh` / `warn` / `stale`.
   - The dashboard only accepts `HIGH` / `MEDIUM` / `LOW`, so it drops the freshness object during normalization.
   - As a result, the dashboard cannot reliably satisfy FR02.83-FR02.85 or the data freshness summary required by FR02.101.
   - Key refs: `backend/replenishment/services/needs_list.py:376`, `backend/replenishment/services/needs_list.py:377`, `frontend/src/app/replenishment/models/stock-status.model.ts:3`, `frontend/src/app/replenishment/stock-status-dashboard/stock-status-dashboard.component.ts:300`, `frontend/src/app/replenishment/stock-status-dashboard/stock-status-dashboard.component.ts:315`, `backend/replenishment/views.py:693`

5. **Demand and planning windows now have a larger backlog gap after FR02.04a**
   - Backlog FR02.04 still defines the default phase windows as SURGE `6h/24h`, STABILIZED `72h/72h`, and BASELINE `720h/168h`.
   - The default code path (`NEEDS_WINDOWS_VERSION=v41`) still uses SURGE `6h/72h`, STABILIZED `72h/168h`, and BASELINE `720h/720h`.
   - New backlog item FR02.04a adds a stronger requirement: only ODPEM national tenant users with `System Admin` or `Director, PEOD` roles may configure those windows, the change must apply globally across all tenants, and the update must capture justification plus prior/new values for audit.
   - The current implementation does not satisfy that control model. Runtime calculation still reads static environment/versioned constants, the data model stores phase config per `event_id`, and there is no visible API/UI path for privileged global window administration.
   - The existing audit fields and phase-history log do not capture dedicated before/after window-value changes with justification for this setting.
   - Key refs: `backend/replenishment/rules.py:47`, `backend/replenishment/rules.py:48`, `backend/replenishment/rules.py:49`, `backend/replenishment/rules.py:50`, `backend/replenishment/rules.py:178`, `backend/replenishment/rules.py:189`, `backend/replenishment/views.py:88`, `backend/replenishment/models.py:39`, `backend/replenishment/models.py:51`, `backend/replenishment/models.py:73`, `backend/replenishment/models.py:80`, `backend/replenishment/workflow_store_db.py:97`

6. **The wizard that the dashboard routes users into is not connected to real draft/save/submit APIs**
   - Step 3 still simulates both save and submit with timers and success toasts.
   - The dashboard therefore routes users into a workflow that looks complete, but does not actually create or submit needs lists.
   - The older preview screen contains the real API calls, so the module currently has two competing flows: one functional but legacy, one improved but mock-only.
   - Key refs: `frontend/src/app/replenishment/stock-status-dashboard/stock-status-dashboard.component.ts:502`, `frontend/src/app/replenishment/needs-list-wizard/steps/step3-submit/submit-step.component.ts:493`, `frontend/src/app/replenishment/needs-list-wizard/steps/step3-submit/submit-step.component.ts:512`, `frontend/src/app/replenishment/needs-list-preview/needs-list-preview.component.ts:187`, `frontend/src/app/replenishment/needs-list-preview/needs-list-preview.component.ts:279`

7. **The dashboard's mobile quick action can launch the wizard without a selected warehouse**
   - The FAB always calls `generateNeedsList()` with no warehouse in multi-warehouse mode.
   - The wizard converts that to an empty `warehouse_ids` list, and Step 1 requires at least one selected warehouse before the user can proceed.
   - This breaks the "quick action from dashboard" path for the most mobile-centric entry point.
   - Key refs: `frontend/src/app/replenishment/stock-status-dashboard/stock-status-dashboard.component.html:471`, `frontend/src/app/replenishment/stock-status-dashboard/stock-status-dashboard.component.ts:502`, `frontend/src/app/replenishment/needs-list-wizard/services/wizard-state.service.ts:28`

8. **The system/security architecture document is no longer aligned with the EP-02 implementation stack**
   - The security architecture still describes Flask, Flask-Login, Flask-Limiter, Flask-WTF, and SQLAlchemy as the active controls.
   - EP-02 is implemented as a Django/DRF module with custom bearer-token auth and custom RBAC resolution.
   - Until this document is updated, we do not have a trustworthy architecture baseline for reviewing EP-02 controls such as throttling, CSRF posture, or backend trust boundaries.
   - Key refs: `docs/security/SECURITY_ARCHITECTURE.md:13`, `docs/security/SECURITY_ARCHITECTURE.md:21`, `backend/dmis_api/settings.py:21`, `backend/dmis_api/settings.py:27`, `backend/api/authentication.py:84`, `backend/api/authentication.py:102`

## Dashboard-First Recommendation

Before improving the dashboard UI, lock down three backend contracts:

1. **Pick one authoritative workflow state model**
   - Align requirements, schema, backend controllers, tests, and Angular types on one status vocabulary.

2. **Pick one authoritative persistence path**
   - Either finish and wire `workflow_store_db.py`, or explicitly defer DB persistence and stop presenting the module as production-ready.

3. **Normalize dashboard input data**
   - Fix freshness enum mapping, phase windows, and default horizon lead times before changing visual hierarchy.

After those are fixed, the dashboard should be the first feature implementation target:

1. Repair freshness rendering and stale-data alerts
2. Fix the mobile/dashboard CTA so it always opens a valid wizard scope
3. Decide whether the dashboard should launch the real preview flow or a fully wired wizard
4. Only then refine sorting, filtering, and visual emphasis for critical items

## Verification Notes

- I could not execute the Django test suite in this workspace because Django is not installed in the available Python environment.
- Attempted command: `python manage.py test replenishment`
- Result: `ModuleNotFoundError: No module named 'django'`
