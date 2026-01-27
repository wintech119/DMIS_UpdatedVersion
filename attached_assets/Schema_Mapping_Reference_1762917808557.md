# DRIMS Database Schema Mapping - Quick Reference

## Table Name Mappings

This document provides a quick reference for mapping between DRIMS application concepts and the aidmgmt-3.sql database tables.

### Primary Mappings

| DRIMS Application Term | Database Table | Primary Key | Description |
|------------------------|----------------|-------------|-------------|
| **Warehouse/Location/Depot/Hub** | `warehouse` | `warehouse_id` | Storage facilities (MAIN, HUB, SUB-HUB, AGENCY types) |
| **Event/Disaster Event** | `event` | `event_id` | Disaster/emergency events (Hurricane, Earthquake, etc.) |
| **Item/Relief Item** | `item` | `item_id` | Relief supply items with SKU codes |
| **Donor** | `donor` | `donor_id` | Individual or organization donors |
| **Agency** | `agency` | `agency_id` | Request-only locations (shelters, community centers) |
| **Inventory/Stock** | `inventory` | `inventory_id` | Stock levels by warehouse and item |
| **Storage Location** | `location` | `location_id` | Physical locations within warehouses |
| **Needs List/Relief Request** | `reliefrqst` | `reliefrqst_id` | Relief requests from agencies |
| **Needs List Item/Request Item** | `reliefrqst_item` | `(reliefrqst_id, item_id)` | Line items in relief requests |
| **Fulfilment/Relief Package** | `reliefpkg` | `reliefpkg_id` | Packages prepared for dispatch |
| **Fulfilment Line Item** | `reliefpkg_item` | `(reliefpkg_id, fr_inventory_id, item_id)` | Items in relief packages |
| **Receipt/Distribution Intake** | `dbintake` | `(reliefpkg_id, inventory_id)` | Receipt of packages at destination |
| **Receipt Item** | `dbintake_item` | `(reliefpkg_id, inventory_id, item_id)` | Items received |
| **Donation** | `donation` | `donation_id` | Donations received |
| **Donation Item** | `donation_item` | `(donation_id, item_id)` | Items in donations |
| **Donation Intake** | `dnintake` | `(donation_id, inventory_id)` | Intake of donations to warehouse |
| **Transfer** | `transfer` | `transfer_id` | Transfers between warehouses |
| **Transfer Item** | `transfer_item` | `(transfer_id, item_id)` | Items in transfer |

### DRIMS Extension Tables (Not in aidmgmt-3.sql)

**Modern Workflow Tables:**

| Table | Primary Key | Purpose |
|-------|-------------|---------|
| `needs_list` | `id` | Enhanced needs list workflow (modern UI) |
| `needs_list_item` | `id` | Line items in needs lists |
| `fulfilment` | `id` | Fulfilment packages for needs lists |
| `fulfilment_line_item` | `id` | Items allocated from warehouses |
| `fulfilment_edit_log` | `id` | Audit log for fulfilment changes |
| `dispatch_manifest` | `id` | Dispatch manifests for shipments |
| `receipt_record` | `id` | Receipt records at destination |
| `distribution_package` | `id` | Alternative distribution workflow |
| `distribution_package_item` | `id` | Items in distribution packages |

**User Management Tables:**

| Table | Primary Key | Purpose |
|-------|-------------|---------|
| `user` | `id` | User authentication and profiles |
| `role` | `id` | Role definitions for RBAC |
| `user_role` | `(user_id, role_id)` | User-to-role assignments |
| `user_warehouse` | `(user_id, warehouse_id)` | User warehouse access control |

**Support Tables:**

| Table | Primary Key | Purpose |
|-------|-------------|---------|
| `notification` | `id` | In-app notifications |
| `transfer_request` | `id` | Enhanced transfer approval workflow |
| `transaction` | `id` | Legacy transaction log (for compatibility) |

### Reference Tables

| Table | Purpose |
|-------|---------|
| `country` | Country codes and names |
| `parish` | Jamaican parishes (14 parishes) |
| `unitofmeasure` | Units of measure (KG, LITRE, BOX, etc.) |
| `itemcatg` | Item categories (FOOD, WATER, MEDICAL, etc.) |
| `custodian` | GOJ custodian agency (ODPEM) |

## Dual Workflow System

DRIMS supports **two parallel workflow systems** for relief operations:

### 1. aidmgmt-3.sql Workflow (Original ODPEM)
- **Request:** `reliefrqst` → `reliefrqst_item`
- **Package:** `reliefpkg` → `reliefpkg_item`
- **Receipt:** `dbintake` → `dbintake_item`
- **Status codes:** CHAR(1) or SMALLINT
- **Audit fields:** Required (create_by_id, create_dtime, etc.)

### 2. DRIMS Workflow (Enhanced Modern)
- **Request:** `needs_list` → `needs_list_item`
- **Package:** `fulfilment` → `fulfilment_line_item`
- **Dispatch:** `dispatch_manifest`
- **Receipt:** `receipt_record`
- **Status codes:** VARCHAR descriptive strings
- **Audit fields:** Simplified (created_by, created_at, etc.)

### Choosing a Workflow

**Use aidmgmt-3.sql workflow if:**
- Need strict compliance with ODPEM standards
- Integration with existing ODPEM systems
- Require detailed verification workflow
- Need complex intake tracking (usable/defective/expired)

**Use DRIMS workflow if:**
- Want modern, user-friendly UI
- Need enhanced features (lock/unlock, edit logs)
- Require multi-warehouse allocation
- Want detailed dispatch manifests

**Can use both:**
- Both workflows can coexist
- Use aidmgmt-3.sql for official records
- Use DRIMS workflow for operations
- Map between systems as needed

## Status Code Mappings

### Event Status (`event.status_code`)
- `A` = Active
- `C` = Closed

### Item Status (`item.status_code`)
- `A` = Active
- `I` = Inactive

### Warehouse Status (`warehouse.status_code`)
- `A` = Active
- `I` = Inactive

### Inventory Status (`inventory.status_code`)
- `A` = Available
- `U` = Unavailable

### Storage Location Status (`location.status_code`)
- `O` = Open
- `C` = Closed

### Donation Status (`donation.status_code`)
- `E` = Entered
- `V` = Verified

### Relief Request Status (`reliefrqst.status_code`)
- `0` = Draft
- `1` = Awaiting approval
- `2` = Cancelled
- `3` = Submitted
- `4` = Denied
- `5` = Part filled
- `6` = Closed
- `7` = Filled

### Relief Request Item Status (`reliefrqst_item.status_code`)
- `R` = Requested
- `U` = Unavailable
- `W` = Waiting availability
- `D` = Denied
- `P` = Partly filled
- `L` = Limit allowed
- `F` = Filled

### Relief Package Status (`reliefpkg.status_code`)
- `P` = Processing
- `C` = Completed
- `V` = Verified
- `D` = Dispatched

### Intake Status (`dnintake.status_code`, `dbintake.status_code`)
- `I` = Incomplete
- `C` = Completed
- `V` = Verified

### Intake Item Status (`dnintake_item.status_code`, `dbintake_item.status_code`)
- `P` = Pending verification
- `V` = Verified

### Transfer Status (`transfer.status_code`)
- `P` = Processing
- `C` = Completed
- `V` = Verified
- `D` = Dispatched

### Urgency Indicator (`reliefrqst.urgency_ind`, `reliefrqst_item.urgency_ind`)
- `L` = Low
- `M` = Medium
- `H` = High
- `C` = Critical

## Key Foreign Key Relationships

### Warehouse → Inventory
```sql
inventory.warehouse_id → warehouse.warehouse_id
```

### Item → Inventory
```sql
inventory.item_id → item.item_id
```

### Relief Request → Agency
```sql
reliefrqst.agency_id → agency.agency_id
```

### Relief Request → Relief Package
```sql
reliefpkg.reliefrqst_id → reliefrqst.reliefrqst_id
```

### Relief Package → Inventory (Destination)
```sql
reliefpkg.to_inventory_id → inventory.inventory_id
```

### Relief Package Item → Inventory (Source)
```sql
reliefpkg_item.fr_inventory_id → inventory.inventory_id
```

### Relief Package → Distribution Intake
```sql
dbintake.reliefpkg_id → reliefpkg.reliefpkg_id
```

### Donation → Donor
```sql
donation.donor_id → donor.donor_id
```

### Donation → Event
```sql
donation.event_id → event.event_id
```

## Audit Fields (Present in Most Tables)

All aidmgmt-3.sql tables include these audit fields:

| Field | Type | Purpose |
|-------|------|---------|
| `create_by_id` | VARCHAR(20) | User who created the record |
| `create_dtime` | TIMESTAMP | Date/time record was created |
| `update_by_id` | VARCHAR(20) | User who last updated the record |
| `update_dtime` | TIMESTAMP | Date/time record was last updated |
| `version_nbr` | INTEGER | Version number for optimistic locking |

Some tables also include verification fields:
- `verify_by_id` (VARCHAR(20)) - User who verified
- `verify_dtime` (TIMESTAMP) - Date/time verified

## Warehouse Types

From `warehouse.warehouse_type`:
- `MAIN` - Central warehouse with full inventory management
- `HUB` - Regional distribution hub
- `SUB-HUB` - Sub-regional distribution point
- `AGENCY` - Request-only location (shelter, community center)

## Event Types

From `event.event_type`:
- `STORM` - Storm/tropical system
- `TORNADO` - Tornado
- `FLOOD` - Flooding
- `TSUNAMI` - Tsunami
- `FIRE` - Fire disaster
- `EARTHQUAKE` - Earthquake
- `WAR` - War/conflict
- `EPIDEMIC` - Epidemic/pandemic

## Important Constraints

### Naming Conventions
- All warehouse names, agency names, donor names, item names must be UPPERCASE
- Item descriptions use CITEXT (case-insensitive text)

### Quantity Fields
- All quantity fields are DECIMAL(12,2)
- Must be >= 0.00
- Reserved quantity must be <= usable quantity in inventory

### Date Constraints
- Most date fields have CHECK constraint: `<= CURRENT_DATE`
- Cannot enter future dates for events that have occurred

### Status Workflows
- Status transitions are enforced through CHECK constraints
- Some status changes require associated fields (e.g., closed event requires closed_date)

## Database Extensions Required

```sql
CREATE EXTENSION IF NOT EXISTS citext;
```

Required for case-insensitive text in `item.item_desc`.

## Default Values

- Default country: Jamaica (country_id = 388)
- Default custodian: ODPEM
- Default UOM: UNIT
- Default timezone: America/Jamaica (EST/GMT-5)

---

**For complete schema details, see:**
- `DRIMS_Complete_Schema.sql` - Complete SQL schema with all tables
- `DRIMS_Requirements_Document.md` - Full requirements with functional specifications
- `aidmgmt-3.sql` - Original ODPEM schema source
