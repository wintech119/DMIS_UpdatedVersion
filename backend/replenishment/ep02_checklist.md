# EP-02 Acceptance Criteria Checklist

Short mapping of EP-02 acceptance criteria to current implementation state.

| Criterion | Status | Code Location | Notes |
| --- | --- | --- | --- |
| AC01 API returns required fields (required_qty, time_to_stockout, freshness_state, horizons, warnings) | Pass | `backend/replenishment/services/needs_list.py` | Added fields to item payload. |
| AC02 Time-to-stockout shows “N/A - No current demand” when burn is 0 | Pass | `backend/replenishment/services/needs_list.py` (`compute_time_to_stockout_hours`) | String returned when burn is zero. |
| AC03 Freshness state is Fresh/Warn/Stale/Unknown (Unknown if no timestamp) | Pass | `backend/replenishment/services/needs_list.py` (`compute_freshness_state`) | Unknown when inventory timestamp is missing. |
| AC04 Horizon A/B/C recommendations returned; C is null when procurement unavailable | Pass | `backend/replenishment/services/needs_list.py` (`allocate_horizons`) | C is null with warnings. |
| AC05 Triggers booleans included (activate_B/activate_C/activate_all) | Partial | `backend/replenishment/services/needs_list.py` (`build_preview_items`) | Trigger rules implemented; critical item flag not modeled so SURGE+critical is best-effort with warning `critical_flag_unavailable`. |
| AC06 UI shows required qty, time-to-stockout, freshness badge, estimated badge | Pass | `frontend/src/app/replenishment/needs-list-preview/needs-list-preview.component.*` | Estimated badge shown on burn-rate. |
| AC07 Warnings panel shows top-level + expandable per-item warnings | Pass | `frontend/src/app/replenishment/needs-list-preview/needs-list-preview.component.html` | Uses `<details>` per item. |
| AC08 Donation inbound unmodeled warning is surfaced while Horizon B remains recommended | Pass | `backend/replenishment/services/data_access.py` + UI warnings panel | Inbound donations remain 0 with warning. |
