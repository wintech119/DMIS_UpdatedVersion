# DMIS Multi-Tenancy + EP-02 Test Data Documentation

## Overview

This package implements a **graceful migration strategy** for DMIS multi-tenancy, creating a new `tenant` table as the canonical organizational registry while preserving the existing `custodian` table and all its dependencies.

## Files

| File | Purpose |
|------|---------|
| `dmis_test_data.sql` | Creates schema extensions + migrates custodians + seeds test data |
| `dmis_test_data_purge.sql` | Removes test data while preserving schema structure |

## Usage

```bash
# Create schema and test data
psql -d dmis -f dmis_test_data.sql

# Remove test data (keeps schema)
psql -d dmis -f dmis_test_data_purge.sql
```

---

## Migration Strategy

### The Problem
The existing `custodian` table is referenced by:
- `warehouse.custodian_id` (FK)
- `donation.custodian_id` (FK)
- Potentially other modules

Dropping or replacing `custodian` would break these dependencies.

### The Solution: Graceful Bridge Migration

```
┌─────────────────────────────────────────────────────────────────┐
│                     MULTI-TENANCY SCHEMA                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────┐                                            │
│  │     TENANT       │  ← Canonical organization registry         │
│  │ (NEW - Primary)  │                                            │
│  └────────┬─────────┘                                            │
│           │                                                      │
│           │ tenant_id (FK)                                       │
│           ▼                                                      │
│  ┌──────────────────┐      ┌──────────────────┐                  │
│  │   CUSTODIAN      │      │   WAREHOUSE      │                  │
│  │ (Preserved +     │─────▶│ (Preserved +     │                  │
│  │  tenant_id added)│      │  tenant_id added)│                  │
│  └──────────────────┘      └──────────────────┘                  │
│           │                         │                            │
│           │ custodian_id (existing) │                            │
│           ▼                         │                            │
│  ┌──────────────────┐               │                            │
│  │    DONATION      │               │  (existing FK preserved)   │
│  │ (unchanged)      │◀──────────────┘                            │
│  └──────────────────┘                                            │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Migration Steps (Automatic)

1. **Create `tenant` table** with organizational attributes from Stakeholder Analysis
2. **Add `tenant_id` to `custodian`** as optional FK (bridge column)
3. **Add `tenant_id` to `warehouse`** for direct tenant lookup
4. **Auto-migrate existing custodians** to tenant records
5. **Link custodians to tenants** via the new FK
6. **Derive warehouse.tenant_id** from custodian linkage

### Benefits

✅ **No breaking changes** - All existing FKs continue to work  
✅ **Gradual migration** - New code can use tenant_id, old code uses custodian_id  
✅ **Eventual cleanup** - custodian table can be removed after full migration  
✅ **Rich attributes** - tenant table supports DMIS Access Matrix requirements  

---

## Schema Changes

### New Tables

| Table | Purpose |
|-------|---------|
| `tenant` | Canonical organization registry with multi-tenancy attributes |
| `tenant_config` | Tenant-specific configuration (approval thresholds, etc.) |
| `tenant_user` | Maps users to tenants with access levels |
| `tenant_warehouse` | Maps warehouses to tenants (supports shared model) |
| `data_sharing_agreement` | Cross-tenant data visibility permissions |
| `event_phase` | Event phase tracking (SURGE/STABILIZED/BASELINE) |
| `needs_list` | Supply Replenishment needs list headers |
| `needs_list_item` | Needs list line items with Three Horizons logic |
| `warehouse_sync_status` | Tracks data freshness for offline scenarios |

### Modified Tables

| Table | Change |
|-------|--------|
| `custodian` | Added `tenant_id` FK (nullable, for migration) |
| `warehouse` | Added `tenant_id` FK (nullable, for direct lookup) |

---

## Tenant Types (From Stakeholder Analysis v1.6)

| Type | Description | Data Scope | Examples |
|------|-------------|------------|----------|
| `NATIONAL` | National agencies | NATIONAL_DATA | ODPEM, NDRMC, PIOJ |
| `MILITARY` | Defense forces | OWN_DATA | JDF, JCF |
| `MINISTRY` | Government ministries | NATIONAL_DATA | MLSS, MHW, MFPS |
| `PARISH` | Municipal corporations | PARISH_DATA | KSAMC, Portland MC |
| `EXTERNAL` | NGOs & partners | OWN_DATA | JRC, FFP, UNOPS |
| `INFRASTRUCTURE` | Utilities | OWN_DATA | JPS, NWC |
| `PUBLIC` | Dashboard access | OWN_DATA | Public transparency |

---

## Tenant Configuration Keys

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `APPROVAL_THRESHOLD_JMD` | DECIMAL | 3,000,000 | Procurement approval threshold |
| `EMERGENCY_APPROVAL_LIMIT_JMD` | DECIMAL | 100,000,000 | PPA 2015 S24 emergency limit |
| `SURGE_DEMAND_WINDOW_HOURS` | INTEGER | 6 | Burn rate lookback for SURGE |
| `STABILIZED_PLANNING_WINDOW_HOURS` | INTEGER | 168 | Planning horizon (7 days) |
| `BUFFER_MULTIPLIER` | DECIMAL | 1.25 | Safety stock (25%) |
| `DATA_FRESHNESS_WARNING_HOURS` | INTEGER | 4 | Warning threshold |
| `DATA_FRESHNESS_STALE_HOURS` | INTEGER | 24 | Stale data threshold |

---

## Access Levels (From DMIS Access Matrix)

| Level | Description | Typical Use |
|-------|-------------|-------------|
| `ADMIN` | Full system administration | System administrators |
| `FULL` | Full access to tenant data | Logistics managers |
| `STANDARD` | Normal operational access | Warehouse officers |
| `LIMITED` | Restricted access | Field workers |
| `READ_ONLY` | View-only access | Dashboard users |

---

## Three Horizons Logic (EP-02)

| Horizon | Code | Timeframe | Fulfillment Method |
|---------|------|-----------|-------------------|
| A | Transfer | Hours | Inter-warehouse transfer |
| B | Donation | Days | Accept pending donations |
| C | Procurement | Weeks | Purchase from suppliers |

---

## Event Phases

| Phase | Demand Window | Planning Horizon | Trigger |
|-------|---------------|------------------|---------|
| SURGE | 6 hours | 72 hours | Event start |
| STABILIZED | 72 hours | 168 hours | Auto/manual @ 72h |
| BASELINE | Historical | Ongoing | Manual transition |

---

## Data Freshness Levels

| Level | Threshold | UI Indicator | Burn Rate Source |
|-------|-----------|--------------|------------------|
| HIGH | < 4 hours | Green | CALCULATED |
| MEDIUM | 4-12 hours | Yellow | CALCULATED (warning) |
| LOW | 12-24 hours | Orange | BASELINE fallback |
| STALE | > 24 hours | Red | BASELINE + acknowledgment |

---

## Query Examples

### Get tenant for a warehouse
```sql
-- Via direct FK (preferred after migration)
SELECT t.* FROM tenant t
JOIN warehouse w ON w.tenant_id = t.tenant_id
WHERE w.warehouse_id = :warehouse_id;

-- Via custodian bridge (backward compatible)
SELECT t.* FROM tenant t
JOIN custodian c ON c.tenant_id = t.tenant_id
JOIN warehouse w ON w.custodian_id = c.custodian_id
WHERE w.warehouse_id = :warehouse_id;
```

### Get warehouses visible to a tenant
```sql
SELECT w.* FROM warehouse w
JOIN tenant_warehouse tw ON tw.warehouse_id = w.warehouse_id
WHERE tw.tenant_id = :tenant_id
AND tw.effective_date <= CURRENT_DATE
AND (tw.expiry_date IS NULL OR tw.expiry_date >= CURRENT_DATE);
```

### Get tenant configuration value
```sql
SELECT config_value FROM tenant_config
WHERE tenant_id = :tenant_id
AND config_key = :key
AND effective_date <= CURRENT_DATE
AND (expiry_date IS NULL OR expiry_date >= CURRENT_DATE)
ORDER BY effective_date DESC
LIMIT 1;
```

---

## Future Migration Path

Once all code is updated to use `tenant_id`:

1. **Remove `custodian_id` FK** from `warehouse` and `donation`
2. **Migrate remaining custodian data** to appropriate tenant attributes
3. **Drop `custodian` table**
4. **Clean up bridge columns**

This should be done incrementally using the Strangler Fig Pattern as outlined in the EP-02 completion strategy.

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 2.0 | 2026-02-13 | Graceful custodian migration, tenant_id bridge columns |
| 1.0 | 2026-02-13 | Initial multi-tenancy schema (replaced) |
