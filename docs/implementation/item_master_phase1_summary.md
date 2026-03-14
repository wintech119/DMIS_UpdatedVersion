# Item Master Phase 1 - Implementation Summary

## Scope

Unified Item Master with IFRC taxonomy integration, canonical item codes, and L1/L2/L3 catalog maintenance.

## Backend Assumptions

### Canonical Item Code Derivation
- On create/update with `ifrc_item_ref_id`, `item_code` is overwritten with the IFRC reference's `ifrc_code`.
- Any user-supplied `item_code` on create is preserved as `legacy_item_code`.
- On update of a legacy item (no prior mapping), the existing `item_code` is copied to `legacy_item_code` before overwrite.
- `item_code` is unique; a 409 conflict response is returned if another item already holds the derived code.

### UOM Default Row
- `_ensure_default_item_uom_option` runs after every item create/update that includes `default_uom_code`.
- Uses `ON CONFLICT (item_id, uom_code) DO UPDATE` to upsert the default row with `conversion_factor=1`, `is_default=TRUE`.
- Clears `is_default` on all other UOM rows for the same item.

### Classification Audit
- `_log_classification_change` records family/reference changes to `item_classification_audit`.
- Triggers on create (if mapped) and on update when `ifrc_family_id` or `ifrc_item_ref_id` changes.
- Stores old and new values plus actor and timestamp.

### Suggestion Resolution
- `resolve_ifrc_suggestion` marks a suggestion as APPLIED/REJECTED and optionally updates the item's taxonomy fields.
- APPLIED resolution calls the full item update pipeline (validation, canonical code, audit).

### IFRC Reference Metadata (Phase 1 Migration 0007)
- `ifrc_item_reference` table extended with `size_weight`, `form`, `material` columns.
- Seed data includes these fields from the IFRC taxonomy payload.
- Frontend displays them as read-only in the "Find IFRC Match" helper panel.

## Frontend Contract Dependencies

| API Endpoint | Frontend Consumer | Required Fields |
|---|---|---|
| `GET /api/v1/masterdata/items/categories/lookup` | L1 category dropdown | `value`, `label`, `status_code` |
| `GET /api/v1/masterdata/items/ifrc-families/lookup?category_id=X` | L2 family dropdown | `value`, `label` |
| `GET /api/v1/masterdata/items/ifrc-references/lookup?ifrc_family_id=X` | L3 reference dropdown + helper | `value`, `label`, `ifrc_code`, `size_weight`, `form`, `material` |
| `POST /api/v1/masterdata/items/` | Item create | Returns `record` or 409 with `ITEM_CANONICAL_CONFLICT` |
| `PATCH /api/v1/masterdata/items/{pk}` | Item update | Same conflict handling |
| `GET/POST /api/v1/masterdata/ifrc_families/` | Catalog CRUD | Standard masterdata pattern |
| `GET/POST /api/v1/masterdata/ifrc_item_references/` | Catalog CRUD | Standard masterdata pattern |

## Tables Introduced

| Table | PK | Purpose |
|---|---|---|
| `ifrc_family` | `ifrc_family_id` | L2 IFRC product families grouped by L1 category |
| `ifrc_item_reference` | `ifrc_item_ref_id` | L3 IFRC reference items with spec metadata |
| `item_uom_option` | `(item_id, uom_code)` | Per-item UOM conversion options |
| `item_classification_audit` | `audit_id` | Audit trail for taxonomy changes |

## Migrations

| Migration | Description |
|---|---|
| 0005 | Create `ifrc_family`, `ifrc_item_reference`, `item_uom_option`, `item_classification_audit`; add FK columns to `item` |
| 0006 | Add `legacy_item_code` to `item`; unique index on `ifrc_item_ref_id`; backfill canonical codes |
| 0007 | Add `size_weight`, `form`, `material` to `ifrc_item_reference`; re-sync seed data |
