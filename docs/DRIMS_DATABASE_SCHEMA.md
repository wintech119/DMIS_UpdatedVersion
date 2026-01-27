# DRIMS Database Schema
**Generated:** November 12, 2025  
**Database:** PostgreSQL 16+  
**Total Tables:** 42  
**Total Size:** ~1.6 MB

---

## Overview

The DRIMS database contains 40 operational tables plus 2 supporting tables (country, parish), organized into the following functional areas:

### Core Entity Management (9 tables)
- **agency** - Relief agencies (DISTRIBUTOR/SHELTER types)
- **custodian** - Warehouse custodians
- **donor** - Individual and organizational donors
- **event** - Disaster events
- **item** - Relief supply catalog
- **itemcatg** - Item categories
- **unitofmeasure** - Units of measurement
- **warehouse** - Storage facilities
- **user** - System users with RBAC

### Inventory Management (3 tables)
- **inventory** - Stock levels by warehouse/item
- **location** - Bin-level inventory tracking
- **item_location** - Item-to-location mapping

### AIDMGMT Relief Workflow (6 tables)
- **reliefrqst** - Relief requests from agencies
- **reliefrqst_item** - Requested items
- **reliefpkg** - Prepared relief packages
- **reliefpkg_item** - Package line items
- **dbintake** - Distribution intake records
- **dbintake_item** - Intake line items

### Donation Management (4 tables)
- **donation** - Donation records
- **donation_item** - Donated items
- **dnintake** - Donation intake
- **dnintake_item** - Donation intake line items

### Transfer Management (8 tables)
- **transfer** - Inter-warehouse transfers
- **transfer_item** - Transfer line items
- **transfer_request** - Transfer requests
- **xfintake** - Transfer intake
- **xfintake_item** - Transfer intake items
- **xfreturn** - Return transfers
- **rtintake** - Return intake
- **rtintake_item** - Return intake items

### Distribution Packages (2 tables)
- **distribution_package** - Distribution packages
- **distribution_package_item** - Package items

### Agency Account Management (2 tables)
- **agency_account_request** - Agency account requests with workflow
- **agency_account_request_audit** - Immutable audit trail

### System & Security (6 tables)
- **role** - User roles
- **user_role** - User-role assignments
- **user_warehouse** - User-warehouse permissions
- **notification** - System notifications
- **transaction** - Transaction log
- **parish** - Jamaican parishes (reference)
- **country** - Countries (reference)

---

## Table Details

### 1. AGENCY
**Purpose:** Relief agencies that request and receive disaster relief supplies

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| agency_id | integer | NO | | Primary key |
| agency_name | varchar(120) | NO | | Unique agency name (uppercase) |
| address1_text | varchar(255) | NO | | Street address |
| address2_text | varchar(255) | YES | | Additional address |
| parish_code | char(2) | NO | | Parish code (FK to parish) |
| contact_name | varchar(50) | NO | | Contact person |
| phone_no | varchar(20) | NO | | Phone number |
| email_text | varchar(100) | YES | | Email address |
| agency_type | varchar(16) | NO | | DISTRIBUTOR or SHELTER |
| ineligible_event_id | integer | YES | | Event agency cannot participate in (FK) |
| status_code | char(1) | NO | | A=Active, I=Inactive |
| warehouse_id | integer | YES | | Assigned warehouse (FK) - NULL for SHELTER, required for DISTRIBUTOR |
| create_by_id | varchar(20) | NO | | Created by user |
| create_dtime | timestamp | NO | | Creation timestamp |
| update_by_id | varchar(20) | NO | | Updated by user |
| update_dtime | timestamp | NO | | Update timestamp |
| version_nbr | integer | NO | | Optimistic locking version |

**Constraints:**
- PRIMARY KEY: agency_id
- UNIQUE: agency_name
- FOREIGN KEY: parish_code → parish(parish_code)
- FOREIGN KEY: ineligible_event_id → event(event_id)
- FOREIGN KEY: warehouse_id → warehouse(warehouse_id)
- CHECK: c_agency_5 - SHELTER must have NULL warehouse_id, DISTRIBUTOR must have non-NULL warehouse_id

---

### 2. AGENCY_ACCOUNT_REQUEST
**Purpose:** Agency account creation workflow with state machine (S→R→A/D)

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| request_id | integer | NO | | Primary key |
| agency_name | varchar(120) | NO | | Requested agency name |
| contact_name | varchar(80) | NO | | Contact person name |
| contact_phone | varchar(20) | NO | | Contact phone |
| contact_email | citext | NO | | Contact email (case-insensitive) |
| reason_text | varchar(255) | NO | | Reason for account |
| agency_id | integer | YES | | Linked agency after approval (FK) |
| user_id | integer | YES | | Linked user after provisioning (FK) |
| status_code | char(1) | NO | | S=Submitted, R=Review, A=Approved, D=Denied |
| status_reason | varchar(255) | YES | | Reason for denial |
| created_by_id | integer | NO | | System user who created (FK) |
| created_at | timestamp | NO | CURRENT_TIMESTAMP | Creation time |
| updated_by_id | integer | NO | | Last updater (FK) |
| updated_at | timestamp | NO | CURRENT_TIMESTAMP | Last update time |
| version_nbr | integer | NO | 1 | Optimistic locking |

**Constraints:**
- PRIMARY KEY: request_id
- UNIQUE: uk_aar_active_email - partial unique on lower(contact_email) WHERE status_code IN ('S', 'R')
- FOREIGN KEY: agency_id → agency(agency_id)
- FOREIGN KEY: user_id → user(id)
- FOREIGN KEY: created_by_id → user(id)
- FOREIGN KEY: updated_by_id → user(id)
- CHECK: status_code IN ('S', 'R', 'A', 'D')

**Indexes:**
- dk_aar_status_created ON (status_code, created_at)
- uk_aar_active_email ON lower(contact_email) WHERE status IN ('S','R')

**Triggers:**
- set_updated_at() - Automatically updates updated_at timestamp

---

### 3. AGENCY_ACCOUNT_REQUEST_AUDIT
**Purpose:** Immutable audit log for all agency account workflow events

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| audit_id | integer | NO | | Primary key |
| request_id | integer | NO | | Request being audited (FK) |
| event_type | varchar(24) | NO | | submitted, moved_to_review, approved, denied, provisioned |
| event_notes | varchar(255) | YES | | Additional notes |
| actor_user_id | integer | NO | | User who performed action (FK) |
| event_dtime | timestamp | NO | CURRENT_TIMESTAMP | Event timestamp |
| version_nbr | integer | NO | 1 | Version number |

**Constraints:**
- PRIMARY KEY: audit_id
- FOREIGN KEY: request_id → agency_account_request(request_id)
- FOREIGN KEY: actor_user_id → user(id)

**Indexes:**
- dk_aar_audit_req_time ON (request_id, event_dtime)

---

### 4. CUSTODIAN
**Purpose:** Organizations responsible for warehouse management

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| custodian_id | integer | NO | | Primary key |
| custodian_name | varchar(120) | NO | 'ODPEM' | Custodian name (unique, uppercase) |
| address1_text | varchar(255) | NO | | Street address |
| address2_text | varchar(255) | YES | | Additional address |
| parish_code | char(2) | NO | | Parish code (FK) |
| contact_name | varchar(50) | NO | | Contact person |
| phone_no | varchar(20) | NO | | Phone number |
| email_text | varchar(100) | YES | | Email address |
| create_by_id | varchar(20) | NO | | Created by |
| create_dtime | timestamp | NO | | Creation time |
| update_by_id | varchar(20) | NO | | Updated by |
| update_dtime | timestamp | NO | | Update time |
| version_nbr | integer | NO | | Optimistic locking |

**Constraints:**
- PRIMARY KEY: custodian_id
- UNIQUE: custodian_name
- FOREIGN KEY: parish_code → parish(parish_code)

---

### 5. DONOR
**Purpose:** Individual and organizational donors

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| donor_id | integer | NO | identity | Primary key (auto-generated) |
| donor_code | varchar(16) | NO | | Donor code (e.g., ORG-00001, IND-00001) |
| donor_name | varchar(255) | NO | | Donor name (unique, uppercase) |
| org_type_desc | varchar(30) | YES | | Organization type |
| address1_text | varchar(255) | NO | | Street address |
| address2_text | varchar(255) | YES | | Additional address |
| country_id | smallint | NO | 388 | Country (FK, default=Jamaica) |
| phone_no | varchar(20) | NO | | Phone number |
| email_text | varchar(100) | YES | | Email address |
| create_by_id | varchar(20) | NO | | Created by |
| create_dtime | timestamp | NO | | Creation time |
| update_by_id | varchar(20) | NO | | Updated by |
| update_dtime | timestamp | NO | | Update time |
| version_nbr | integer | NO | | Optimistic locking |

**Constraints:**
- PRIMARY KEY: donor_id
- UNIQUE: donor_name (uk_donor_1)
- FOREIGN KEY: country_id → country(country_id)
- CHECK: donor_code must be uppercase (c_donor_1)
- CHECK: donor_name must be uppercase (c_donor_2)

**Migration Notes:**
- donor_type column removed (2025-11-17) - replaced with donor_code
- donor_code format: "ORG-XXXXX" for organizations, "IND-XXXXX" for individuals

---

### 6. EVENT
**Purpose:** Disaster events triggering relief operations

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| event_id | integer | NO | | Primary key |
| event_type | varchar(16) | NO | | HURRICANE, FLOOD, EARTHQUAKE, etc. |
| start_date | date | NO | | Event start date |
| event_name | varchar(60) | NO | | Event name (uppercase) |
| event_desc | varchar(255) | NO | | Brief description |
| impact_desc | text | NO | | Detailed impact description |
| status_code | char(1) | NO | | A=Active, C=Closed |
| closed_date | date | YES | | Date event closed |
| reason_desc | varchar(255) | YES | | Closure reason |
| create_by_id | varchar(20) | NO | | Created by |
| create_dtime | timestamp | NO | | Creation time |
| update_by_id | varchar(20) | NO | | Updated by |
| update_dtime | timestamp | NO | | Update time |
| version_nbr | integer | NO | | Optimistic locking |

**Constraints:**
- PRIMARY KEY: event_id

---

### 7. ITEM
**Purpose:** Relief supply catalog (master item list)

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| item_id | integer | NO | | Primary key |
| item_name | varchar(60) | NO | | Item name (unique, uppercase) |
| sku_code | varchar(30) | NO | | SKU code (unique, uppercase) |
| category_code | varchar(30) | NO | | Category (FK to itemcatg) |
| item_desc | text | NO | | Item description |
| reorder_qty | numeric(12,2) | NO | | Reorder threshold |
| default_uom_code | varchar(25) | NO | | Default unit (FK) |
| usage_desc | text | YES | | Usage instructions |
| storage_desc | text | YES | | Storage instructions |
| expiration_apply_flag | boolean | NO | | Does item expire? |
| comments_text | text | YES | | Additional comments |
| status_code | char(1) | NO | | A=Active, I=Inactive |
| create_by_id | varchar(20) | NO | | Created by |
| create_dtime | timestamp | NO | | Creation time |
| update_by_id | varchar(20) | NO | | Updated by |
| update_dtime | timestamp | NO | | Update time |
| version_nbr | integer | NO | | Optimistic locking |

**Constraints:**
- PRIMARY KEY: item_id
- UNIQUE: item_name
- UNIQUE: sku_code
- FOREIGN KEY: category_code → itemcatg(category_code)
- FOREIGN KEY: default_uom_code → unitofmeasure(uom_code)

**Indexes:**
- dk_item_1 ON item_desc

---

### 8. ITEMCATG
**Purpose:** Item categories (FOOD, WATER, HYGIENE, MEDICAL, SHELTER)

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| category_code | varchar(30) | NO | | Primary key (uppercase) |
| category_desc | varchar(60) | NO | | Category description |
| comments_text | text | YES | | Comments |
| create_by_id | varchar(20) | NO | | Created by |
| create_dtime | timestamp | NO | | Creation time |
| update_by_id | varchar(20) | NO | | Updated by |
| update_dtime | timestamp | NO | | Update time |
| version_nbr | integer | NO | | Optimistic locking |

**Constraints:**
- PRIMARY KEY: category_code

---

### 9. UNITOFMEASURE
**Purpose:** Units of measurement (UNIT, KG, LITRE, BOX, SACK)

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| uom_code | varchar(25) | NO | | Primary key (uppercase) |
| uom_desc | varchar(100) | NO | | Description |
| comments_text | text | YES | | Comments |
| create_by_id | varchar(20) | NO | | Created by |
| create_dtime | timestamp | NO | | Creation time |
| update_by_id | varchar(20) | NO | | Updated by |
| update_dtime | timestamp | NO | | Update time |
| version_nbr | integer | NO | | Optimistic locking |

**Constraints:**
- PRIMARY KEY: uom_code

---

### 10. WAREHOUSE
**Purpose:** Storage facilities for relief supplies

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| warehouse_id | integer | NO | | Primary key |
| warehouse_name | varchar(120) | NO | | Warehouse name (uppercase) |
| warehouse_type | varchar(16) | NO | | MAIN, REGIONAL, MOBILE |
| address1_text | varchar(255) | NO | | Street address |
| address2_text | varchar(255) | YES | | Additional address |
| parish_code | char(2) | NO | | Parish code (FK) |
| contact_name | varchar(50) | NO | | Contact person |
| phone_no | varchar(20) | NO | | Phone number |
| email_text | varchar(100) | YES | | Email address |
| custodian_id | integer | NO | | Custodian (FK) |
| status_code | char(1) | NO | | A=Active, I=Inactive |
| reason_desc | varchar(255) | YES | | Status reason |
| create_by_id | varchar(20) | NO | | Created by |
| create_dtime | timestamp | NO | | Creation time |
| update_by_id | varchar(20) | NO | | Updated by |
| update_dtime | timestamp | NO | | Update time |
| version_nbr | integer | NO | | Optimistic locking |

**Constraints:**
- PRIMARY KEY: warehouse_id
- FOREIGN KEY: parish_code → parish(parish_code)
- FOREIGN KEY: custodian_id → custodian(custodian_id)

---

### 11. INVENTORY
**Purpose:** Stock levels by warehouse and item

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| inventory_id | integer | NO | | Primary key |
| warehouse_id | integer | NO | | Warehouse (FK) |
| item_id | integer | NO | | Item (FK) |
| usable_qty | numeric(12,2) | NO | 0 | Available quantity |
| reserved_qty | numeric(12,2) | NO | 0 | Reserved quantity |
| defective_qty | numeric(12,2) | NO | 0 | Defective quantity |
| expired_qty | numeric(12,2) | NO | 0 | Expired quantity |
| uom_code | varchar(25) | NO | | Unit of measure (FK) |
| last_verified_by | varchar(20) | YES | | Last verified by |
| last_verified_date | date | YES | | Last verification date |
| status_code | char(1) | NO | | A=Active, I=Inactive |
| comments_text | text | YES | | Comments |
| create_by_id | varchar(20) | NO | | Created by |
| create_dtime | timestamp | NO | | Creation time |
| update_by_id | varchar(20) | NO | | Updated by |
| update_dtime | timestamp | NO | | Update time |
| version_nbr | integer | NO | | Optimistic locking |

**Constraints:**
- PRIMARY KEY: inventory_id
- UNIQUE: uk_inventory_1 ON (item_id, inventory_id)
- UNIQUE: uk_inventory_2 ON (item_id) WHERE usable_qty > 0
- FOREIGN KEY: warehouse_id → warehouse(warehouse_id)
- FOREIGN KEY: item_id → item(item_id)
- FOREIGN KEY: uom_code → unitofmeasure(uom_code)

**Indexes:**
- dk_inventory_1 ON warehouse_id

---

### 12. LOCATION
**Purpose:** Bin-level inventory tracking within warehouses

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| location_id | integer | NO | | Primary key |
| inventory_id | integer | NO | | Inventory record (FK) |
| location_desc | varchar(255) | NO | | Bin/shelf description (uppercase) |
| status_code | char(1) | NO | | A=Active, I=Inactive |
| comments_text | varchar(255) | YES | | Comments |
| create_by_id | varchar(20) | NO | | Created by |
| create_dtime | timestamp | NO | | Creation time |
| update_by_id | varchar(20) | NO | | Updated by |
| update_dtime | timestamp | NO | | Update time |
| version_nbr | integer | NO | | Optimistic locking |

**Constraints:**
- PRIMARY KEY: location_id
- FOREIGN KEY: inventory_id → inventory(inventory_id)

**Indexes:**
- dk_location_1 ON inventory_id

---

### 13. ITEM_LOCATION
**Purpose:** Many-to-many mapping between items and locations

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| inventory_id | integer | NO | | Inventory (FK) |
| item_id | integer | NO | | Item (FK) |
| location_id | integer | NO | | Location (FK) |
| create_by_id | varchar(20) | NO | | Created by |
| create_dtime | timestamp | NO | | Creation time |

**Constraints:**
- PRIMARY KEY: (item_id, location_id)
- FOREIGN KEY: (item_id, inventory_id) → inventory(item_id, inventory_id)
- FOREIGN KEY: location_id → location(location_id)

**Indexes:**
- dk_item_location_1 ON (inventory_id, location_id)

---

### 14. RELIEFRQST (Relief Request)
**Purpose:** Relief requests from agencies (AIDMGMT workflow step 1)

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| reliefrqst_id | integer | NO | | Primary key |
| agency_id | integer | NO | | Requesting agency (FK) |
| request_date | date | NO | | Request date |
| urgency_ind | char(1) | NO | | H=High, M=Medium, L=Low |
| status_code | smallint | NO | | 10=Draft, 20=Submitted, 30=Under Review, 40=Approved, 50=Rejected, 60=Package Prepared, 70=Dispatched, 80=Delivered |
| eligible_event_id | integer | YES | | Associated event (FK) |
| rqst_notes_text | text | YES | | Request notes |
| review_notes_text | text | YES | | Review notes |
| create_by_id | varchar(20) | NO | | Created by |
| create_dtime | timestamp | NO | | Creation time |
| review_by_id | varchar(20) | YES | | Reviewed by |
| review_dtime | timestamp | YES | | Review time |
| action_by_id | varchar(20) | YES | | Action by |
| action_dtime | timestamp | YES | | Action time |
| version_nbr | integer | NO | | Optimistic locking |

**Constraints:**
- PRIMARY KEY: reliefrqst_id
- FOREIGN KEY: agency_id → agency(agency_id)
- FOREIGN KEY: eligible_event_id → event(event_id)

**Indexes:**
- dk_reliefrqst_1 ON (agency_id, request_date)
- dk_reliefrqst_2 ON (request_date, status_code)
- dk_reliefrqst_3 ON (status_code, urgency_ind)

---

### 15. RELIEFRQST_ITEM
**Purpose:** Line items for relief requests

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| reliefrqst_id | integer | NO | | Request (FK) |
| item_id | integer | NO | | Item (FK) |
| request_qty | numeric(15,4) | NO | | Requested quantity |
| issue_qty | numeric(15,4) | NO | | Issued quantity |
| urgency_ind | char(1) | NO | | H=High, M=Medium, L=Low |
| rqst_reason_desc | varchar(255) | YES | | Reason for request |
| item_notes_text | text | YES | | Item notes |
| status_code | char(1) | NO | | A=Active, I=Inactive |
| create_by_id | varchar(20) | NO | | Created by |
| create_dtime | timestamp | NO | | Creation time |
| update_by_id | varchar(20) | NO | | Updated by |
| update_dtime | timestamp | NO | | Update time |
| version_nbr | integer | NO | | Optimistic locking |

**Constraints:**
- PRIMARY KEY: (reliefrqst_id, item_id)
- FOREIGN KEY: reliefrqst_id → reliefrqst(reliefrqst_id)
- FOREIGN KEY: item_id → item(item_id)

**Indexes:**
- dk_reliefrqst_item_2 ON (item_id, urgency_ind)

---

### 16. RELIEFPKG (Relief Package)
**Purpose:** Prepared relief packages (AIDMGMT workflow step 2)

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| reliefpkg_id | integer | NO | | Primary key |
| to_inventory_id | integer | NO | | Destination inventory (FK) |
| reliefrqst_id | integer | NO | | Source request (FK) |
| start_date | date | NO | CURRENT_DATE | Preparation start date |
| dispatch_dtime | timestamp | YES | | Dispatch timestamp |
| transport_mode | varchar(255) | YES | | Transportation method |
| comments_text | varchar(255) | YES | | Comments |
| status_code | char(1) | NO | | P=Prepared, D=Dispatched, R=Received |
| received_by_id | varchar(20) | NO | | Received by |
| received_dtime | timestamp | YES | | Received timestamp |
| create_by_id | varchar(20) | NO | | Created by |
| create_dtime | timestamp | NO | | Creation time |
| update_by_id | varchar(20) | NO | | Updated by |
| update_dtime | timestamp | YES | | Update time |
| verify_by_id | varchar(20) | NO | | Verified by |
| verify_dtime | timestamp | YES | | Verification time |
| version_nbr | integer | NO | | Optimistic locking |

**Constraints:**
- PRIMARY KEY: reliefpkg_id
- FOREIGN KEY: to_inventory_id → inventory(inventory_id)
- FOREIGN KEY: reliefrqst_id → reliefrqst(reliefrqst_id)

**Indexes:**
- dk_reliefpkg_1 ON start_date
- dk_reliefpkg_3 ON to_inventory_id

---

### 17. RELIEFPKG_ITEM
**Purpose:** Line items for relief packages

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| reliefpkg_id | integer | NO | | Package (FK) |
| fr_inventory_id | integer | NO | | Source inventory (FK) |
| item_id | integer | NO | | Item (FK) |
| item_qty | numeric(15,4) | NO | | Quantity |
| uom_code | varchar(25) | NO | | Unit (FK) |
| reason_text | varchar(255) | YES | | Reason notes |
| create_by_id | varchar(20) | NO | | Created by |
| create_dtime | timestamp | NO | | Creation time |
| update_by_id | varchar(20) | NO | | Updated by |
| update_dtime | timestamp | NO | | Update time |
| version_nbr | integer | NO | | Optimistic locking |

**Constraints:**
- PRIMARY KEY: (reliefpkg_id, fr_inventory_id, item_id)
- FOREIGN KEY: reliefpkg_id → reliefpkg(reliefpkg_id)
- FOREIGN KEY: (fr_inventory_id, item_id) → inventory(inventory_id, item_id)
- FOREIGN KEY: uom_code → unitofmeasure(uom_code)

**Indexes:**
- dk_reliefpkg_item_1 ON (fr_inventory_id, item_id)
- dk_reliefpkg_item_2 ON item_id

---

### 18. DBINTAKE (Distribution Intake)
**Purpose:** Distribution intake records (AIDMGMT workflow step 3)

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| reliefpkg_id | integer | NO | | Package (FK) |
| inventory_id | integer | NO | | Destination inventory (FK) |
| intake_date | date | NO | | Intake date |
| comments_text | varchar(255) | YES | | Comments |
| status_code | char(1) | NO | | P=Pending, C=Complete |
| create_by_id | varchar(20) | NO | | Created by |
| create_dtime | timestamp | NO | | Creation time |
| update_by_id | varchar(20) | NO | | Updated by |
| update_dtime | timestamp | YES | | Update time |
| verify_by_id | varchar(20) | NO | | Verified by |
| verify_dtime | timestamp | YES | | Verification time |
| version_nbr | integer | NO | | Optimistic locking |

**Constraints:**
- PRIMARY KEY: (reliefpkg_id, inventory_id)
- FOREIGN KEY: reliefpkg_id → reliefpkg(reliefpkg_id)
- FOREIGN KEY: inventory_id → inventory(inventory_id)

---

### 19. DBINTAKE_ITEM
**Purpose:** Line items for distribution intake

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| reliefpkg_id | integer | NO | | Package (FK) |
| inventory_id | integer | NO | | Inventory (FK) |
| item_id | integer | NO | | Item (FK) |
| usable_qty | numeric(15,4) | NO | | Usable quantity |
| location1_id | integer | YES | | Usable location (FK) |
| defective_qty | numeric(15,4) | NO | | Defective quantity |
| location2_id | integer | YES | | Defective location (FK) |
| expired_qty | numeric(15,4) | NO | | Expired quantity |
| location3_id | integer | YES | | Expired location (FK) |
| uom_code | varchar(25) | NO | | Unit (FK) |
| status_code | char(1) | NO | | Status |
| comments_text | varchar(255) | YES | | Comments |
| create_by_id | varchar(20) | NO | | Created by |
| create_dtime | timestamp | NO | | Creation time |
| update_by_id | varchar(20) | NO | | Updated by |
| update_dtime | timestamp | NO | | Update time |
| version_nbr | integer | NO | | Optimistic locking |

**Constraints:**
- PRIMARY KEY: (reliefpkg_id, inventory_id, item_id)
- FOREIGN KEY: (reliefpkg_id, inventory_id) → dbintake(reliefpkg_id, inventory_id)
- FOREIGN KEY: location1_id → location(location_id)
- FOREIGN KEY: location2_id → location(location_id)
- FOREIGN KEY: location3_id → location(location_id)
- FOREIGN KEY: uom_code → unitofmeasure(uom_code)

**Indexes:**
- dk_dbintake_item_1 ON (inventory_id, item_id)
- dk_dbintake_item_2 ON item_id

---

### 20. DONATION
**Purpose:** Donation records

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| donation_id | integer | NO | identity | Primary key (auto-generated) |
| donor_id | integer | NO | | Donor (FK) |
| donation_desc | text | NO | | Description |
| event_id | integer | NO | | Event (FK) |
| custodian_id | integer | NO | | Custodian (FK) |
| received_date | date | NO | | Receipt date |
| status_code | char(1) | NO | | Status (E=Entered, V=Verified) |
| comments_text | text | YES | | Comments |
| create_by_id | varchar(20) | NO | | Created by |
| create_dtime | timestamp | NO | | Creation time |
| verify_by_id | varchar(20) | NO | | Verified by |
| verify_dtime | timestamp | NO | | Verification time |
| version_nbr | integer | NO | | Optimistic locking |

**Constraints:**
- PRIMARY KEY: donation_id (pk_donation)
- FOREIGN KEY: donor_id → donor(donor_id) (fk_donation_donor)
- FOREIGN KEY: event_id → event(event_id) (fk_donation_event)
- FOREIGN KEY: custodian_id → custodian(custodian_id) (fk_donation_custodian)
- CHECK: received_date <= CURRENT_DATE (c_donation_1)
- CHECK: status_code IN ('E', 'V') (c_donation_2)

**Migration Notes:**
- Constraint names standardized (2025-11-17) to match naming conventions
- donation_id already configured as identity column

---

### 21. DONATION_ITEM
**Purpose:** Donated items

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| donation_id | integer | NO | | Donation (FK) |
| item_id | integer | NO | | Item (FK) |
| item_qty | decimal(12,2) | NO | | Quantity (must be >= 0.00) |
| uom_code | varchar(25) | NO | | Unit of measure (FK) |
| location_name | text | NO | | Physical location description |
| status_code | char(1) | NO | | Status (P=Pending, V=Verified) |
| comments_text | text | YES | | Comments |
| create_by_id | varchar(20) | NO | | Created by |
| create_dtime | timestamp | NO | | Creation time |
| verify_by_id | varchar(20) | NO | | Verified by |
| verify_dtime | timestamp | NO | | Verification time |
| version_nbr | integer | NO | | Optimistic locking |

**Constraints:**
- PRIMARY KEY: (donation_id, item_id) (pk_donation_item)
- FOREIGN KEY: donation_id → donation(donation_id) (fk_donation_item_donation)
- FOREIGN KEY: item_id → item(item_id) (fk_donation_item_item)
- FOREIGN KEY: uom_code → unitofmeasure(uom_code) (fk_donation_item_unitofmeasure)
- CHECK: item_qty >= 0.00 (c_donation_item_1)
- CHECK: status_code IN ('P', 'V') (c_donation_item_2)

**Migration Notes:**
- Table dropped and recreated (2025-11-17) with standardized constraint names
- Changed item_qty from numeric(15,4) to decimal(12,2) to match specification
- Recreated with explicit FK from dnintake_item maintained

---

### 22. DNINTAKE (Donation Intake)
**Purpose:** Donation intake processing

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| donation_id | integer | NO | | Donation (FK) |
| inventory_id | integer | NO | | Inventory (FK) |
| intake_date | date | NO | | Intake date |
| comments_text | varchar(255) | YES | | Comments |
| status_code | char(1) | NO | | Status |
| create_by_id | varchar(20) | NO | | Created by |
| create_dtime | timestamp | NO | | Creation time |
| update_by_id | varchar(20) | NO | | Updated by |
| update_dtime | timestamp | NO | | Update time |
| verify_by_id | varchar(20) | NO | | Verified by |
| verify_dtime | timestamp | NO | | Verification time |
| version_nbr | integer | NO | | Optimistic locking |

**Constraints:**
- PRIMARY KEY: (donation_id, inventory_id)
- FOREIGN KEY: donation_id → donation(donation_id)
- FOREIGN KEY: inventory_id → inventory(inventory_id)

---

### 23. DNINTAKE_ITEM
**Purpose:** Donation intake line items

[Similar structure to dbintake_item - tracks usable/defective/expired quantities with locations]

---

### 24. TRANSFER
**Purpose:** Inter-warehouse transfers

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| transfer_id | integer | NO | | Primary key |
| fr_inventory_id | integer | NO | | Source inventory (FK) |
| to_inventory_id | integer | NO | | Destination inventory (FK) |
| event_id | integer | YES | | Associated event (FK) |
| transfer_date | date | NO | | Transfer date |
| dispatch_dtime | timestamp | YES | | Dispatch time |
| transport_mode | varchar(255) | YES | | Transport method |
| status_code | char(1) | NO | | Status |
| comments_text | varchar(255) | YES | | Comments |
| create_by_id | varchar(20) | NO | | Created by |
| create_dtime | timestamp | NO | | Creation time |
| update_by_id | varchar(20) | NO | | Updated by |
| update_dtime | timestamp | YES | | Update time |
| version_nbr | integer | NO | | Optimistic locking |

**Constraints:**
- PRIMARY KEY: transfer_id
- FOREIGN KEY: fr_inventory_id → inventory(inventory_id)
- FOREIGN KEY: to_inventory_id → inventory(inventory_id)
- FOREIGN KEY: event_id → event(event_id)

**Indexes:**
- dk_transfer_1 ON transfer_date
- dk_transfer_2 ON fr_inventory_id
- dk_transfer_3 ON to_inventory_id

---

### 25. TRANSFER_ITEM
**Purpose:** Transfer line items

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| transfer_id | integer | NO | | Transfer (FK) |
| item_id | integer | NO | | Item (FK) |
| item_qty | numeric(15,4) | NO | | Quantity |
| uom_code | varchar(25) | NO | | Unit (FK) |
| reason_text | varchar(255) | YES | | Reason |
| create_by_id | varchar(20) | NO | | Created by |
| create_dtime | timestamp | NO | | Creation time |
| update_by_id | varchar(20) | NO | | Updated by |
| update_dtime | timestamp | NO | | Update time |
| version_nbr | integer | NO | | Optimistic locking |

**Constraints:**
- PRIMARY KEY: (transfer_id, item_id)
- FOREIGN KEY: transfer_id → transfer(transfer_id)
- FOREIGN KEY: item_id → item(item_id)
- FOREIGN KEY: uom_code → unitofmeasure(uom_code)

---

### 26. TRANSFER_REQUEST
**Purpose:** Transfer requests

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | integer | NO | | Primary key |
| from_warehouse_id | integer | NO | | Source warehouse (FK) |
| to_warehouse_id | integer | NO | | Destination warehouse (FK) |
| requested_by | varchar(200) | NO | | Requestor |
| requested_at | timestamp | NO | CURRENT_TIMESTAMP | Request time |
| approved_by | varchar(200) | YES | | Approver |
| approved_at | timestamp | YES | | Approval time |
| status | varchar(50) | NO | 'Pending' | Status |
| notes | text | YES | | Notes |
| event_id | integer | YES | | Event (FK) |
| created_at | timestamp | NO | CURRENT_TIMESTAMP | Creation time |

**Constraints:**
- PRIMARY KEY: id
- FOREIGN KEY: from_warehouse_id → warehouse(warehouse_id)
- FOREIGN KEY: to_warehouse_id → warehouse(warehouse_id)
- FOREIGN KEY: event_id → event(event_id)

---

### 27-29. XFINTAKE, XFINTAKE_ITEM (Transfer Intake)
**Purpose:** Transfer intake processing

[Similar structure to dbintake/dbintake_item]

---

### 30-32. XFRETURN, RTINTAKE, RTINTAKE_ITEM (Return Transfers)
**Purpose:** Return transfer processing

[Similar structure to transfer/xfintake workflows]

---

### 33. DISTRIBUTION_PACKAGE
**Purpose:** Alternative distribution package system

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | integer | NO | nextval() | Primary key |
| package_number | varchar(64) | NO | | Unique package number |
| recipient_agency_id | integer | NO | | Recipient agency (FK) |
| assigned_warehouse_id | integer | YES | | Warehouse (FK) |
| event_id | integer | YES | | Event (FK) |
| status | varchar(50) | NO | 'Draft' | Status |
| is_partial | boolean | NO | false | Partial fulfillment flag |
| created_by | varchar(200) | NO | | Creator |
| approved_by | varchar(200) | YES | | Approver |
| approved_at | timestamp | YES | | Approval time |
| dispatched_by | varchar(200) | YES | | Dispatcher |
| dispatched_at | timestamp | YES | | Dispatch time |
| delivered_at | timestamp | YES | | Delivery time |
| notes | text | YES | | Notes |
| created_at | timestamp | NO | CURRENT_TIMESTAMP | Creation time |
| updated_at | timestamp | NO | CURRENT_TIMESTAMP | Update time |

**Constraints:**
- PRIMARY KEY: id
- UNIQUE: package_number
- FOREIGN KEY: recipient_agency_id → agency(agency_id)
- FOREIGN KEY: assigned_warehouse_id → warehouse(warehouse_id)
- FOREIGN KEY: event_id → event(event_id)

---

### 34. DISTRIBUTION_PACKAGE_ITEM
**Purpose:** Distribution package line items

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | integer | NO | nextval() | Primary key |
| package_id | integer | NO | | Package (FK) |
| item_id | integer | NO | | Item (FK) |
| quantity | numeric(15,4) | NO | | Quantity |
| notes | text | YES | | Notes |

**Constraints:**
- PRIMARY KEY: id
- FOREIGN KEY: package_id → distribution_package(id)
- FOREIGN KEY: item_id → item(item_id)

---

### 35. USER
**Purpose:** System users with full account management

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | integer | NO | | Primary key |
| email | citext | NO | | Email (unique, case-insensitive) |
| username | varchar(150) | YES | | Username (unique) |
| password_hash | varchar(255) | NO | | Hashed password |
| password_algo | varchar(20) | YES | 'argon2id' | Hash algorithm |
| password_changed_at | timestamp | YES | | Last password change |
| first_name | varchar(100) | NO | | First name |
| last_name | varchar(100) | NO | | Last name |
| phone | varchar(20) | YES | | Phone number |
| status_code | char(1) | YES | 'A' | A=Active, I=Inactive, L=Locked |
| agency_id | integer | YES | | Agency (FK) |
| is_superuser | boolean | NO | false | Superuser flag |
| is_active | boolean | NO | true | Active flag |
| failed_login_count | smallint | YES | | Failed login attempts |
| lock_until_at | timestamp | YES | | Account lock expiry |
| mfa_enabled | boolean | YES | | MFA enabled flag |
| mfa_secret | varchar(64) | YES | | MFA secret |
| last_login_at | timestamp | YES | | Last login time |
| created_at | timestamp | NO | CURRENT_TIMESTAMP | Creation time |
| updated_at | timestamp | NO | CURRENT_TIMESTAMP | Update time |
| version_nbr | integer | NO | | Optimistic locking |

**Constraints:**
- PRIMARY KEY: id
- UNIQUE: email
- UNIQUE: username
- FOREIGN KEY: agency_id → agency(agency_id)

**Indexes:**
- idx_user_email ON email
- dk_user_agency_id ON agency_id

**Triggers:**
- set_updated_at() - Auto-update timestamp

---

### 36. ROLE
**Purpose:** User roles for RBAC

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | integer | NO | | Primary key |
| code | varchar(50) | NO | | Role code (unique) |
| name | varchar(100) | NO | | Role name |
| description | text | YES | | Description |
| created_at | timestamp | NO | CURRENT_TIMESTAMP | Creation time |

**Constraints:**
- PRIMARY KEY: id
- UNIQUE: code

---

### 37. USER_ROLE
**Purpose:** User-role assignments (many-to-many)

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| user_id | integer | NO | | User (FK) |
| role_id | integer | NO | | Role (FK) |
| assigned_at | timestamp | NO | CURRENT_TIMESTAMP | Assignment time |
| assigned_by | integer | YES | | Assigned by user (FK) |

**Constraints:**
- PRIMARY KEY: (user_id, role_id)
- FOREIGN KEY: user_id → user(id)
- FOREIGN KEY: role_id → role(id)
- FOREIGN KEY: assigned_by → user(id)

---

### 38. USER_WAREHOUSE
**Purpose:** User-warehouse permissions (many-to-many)

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| user_id | integer | NO | | User (FK) |
| warehouse_id | integer | NO | | Warehouse (FK) |
| assigned_at | timestamp | NO | CURRENT_TIMESTAMP | Assignment time |
| assigned_by | integer | YES | | Assigned by user (FK) |

**Constraints:**
- PRIMARY KEY: (user_id, warehouse_id)
- FOREIGN KEY: user_id → user(id)
- FOREIGN KEY: warehouse_id → warehouse(warehouse_id)
- FOREIGN KEY: assigned_by → user(id)

---

### 39. NOTIFICATION
**Purpose:** System notifications for users

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | integer | NO | nextval() | Primary key |
| user_id | integer | NO | | User (FK) |
| warehouse_id | integer | YES | | Warehouse (FK) |
| reliefrqst_id | integer | YES | | Request (FK) |
| title | varchar(200) | NO | | Notification title |
| message | text | NO | | Notification message |
| type | varchar(50) | NO | | Notification type |
| status | varchar(20) | NO | 'unread' | read/unread |
| link_url | varchar(500) | YES | | Link URL |
| payload | text | YES | | JSON payload |
| is_archived | boolean | NO | false | Archived flag |
| created_at | timestamp | NO | CURRENT_TIMESTAMP | Creation time |

**Constraints:**
- PRIMARY KEY: id
- FOREIGN KEY: user_id → user(id)
- FOREIGN KEY: warehouse_id → warehouse(warehouse_id)
- FOREIGN KEY: reliefrqst_id → reliefrqst(reliefrqst_id)

**Indexes:**
- idx_notification_user_status ON (user_id, status, created_at)
- idx_notification_warehouse ON (warehouse_id, created_at)

---

### 40. TRANSACTION
**Purpose:** Transaction log

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | integer | NO | nextval() | Primary key |
| transaction_type | varchar(50) | NO | | Transaction type |
| warehouse_id | integer | YES | | Warehouse (FK) |
| item_id | integer | YES | | Item (FK) |
| quantity | numeric(15,4) | YES | | Quantity |
| donor_id | integer | YES | | Donor (FK) |
| event_id | integer | YES | | Event (FK) |
| notes | text | YES | | Notes |
| transaction_date | date | NO | CURRENT_DATE | Transaction date |
| created_by | varchar(200) | NO | | Creator |
| created_at | timestamp | NO | CURRENT_TIMESTAMP | Creation time |

**Constraints:**
- PRIMARY KEY: id
- FOREIGN KEY: warehouse_id → warehouse(warehouse_id)
- FOREIGN KEY: item_id → item(item_id)
- FOREIGN KEY: donor_id → donor(donor_id)
- FOREIGN KEY: event_id → event(event_id)

---

### 41. PARISH
**Purpose:** Jamaican parishes (reference data)

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| parish_code | char(2) | NO | | Primary key (01-14) |
| parish_name | varchar(40) | NO | | Parish name |

**Constraints:**
- PRIMARY KEY: parish_code

**Data:** 14 parishes (Kingston, St. Andrew, St. Catherine, etc.)

---

### 42. COUNTRY
**Purpose:** Countries (reference data)

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| country_id | smallint | NO | | Primary key |
| country_name | varchar(80) | NO | | Country name |

**Constraints:**
- PRIMARY KEY: country_id

**Data:** Includes Jamaica (388) and other countries

---

## Key Design Patterns

### 1. Optimistic Locking
**All 40 operational tables** include `version_nbr` column for optimistic concurrency control using SQLAlchemy's `version_id_col` feature.

### 2. Audit Fields
Standard audit columns on all tables:
- `create_by_id` / `create_dtime` - Creator and creation time
- `update_by_id` / `update_dtime` - Last updater and update time
- `verify_by_id` / `verify_dtime` - Verifier and verification time (where applicable)

### 3. Status Codes
Most entities use status codes:
- `char(1)`: A=Active, I=Inactive, P=Pending, C=Complete, etc.
- `smallint`: Multi-stage workflows (10, 20, 30, etc.)

### 4. Uppercase Enforcement
All `varchar` text fields are stored in uppercase via application-level enforcement.

### 5. Composite Keys
Many junction and detail tables use composite primary keys for natural relationships.

### 6. DECIMAL Precision
All quantity fields use `DECIMAL(12,2)` or `DECIMAL(15,4)` for precision.

---

## Database Functions & Triggers

### set_updated_at()
**Purpose:** Automatically update `updated_at` timestamp on row changes

**Applies to:**
- agency_account_request
- user

**Implementation:**
```sql
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

---

## Summary Statistics

| Metric | Value |
|--------|-------|
| **Total Tables** | 42 |
| **Total Columns** | 672 |
| **Total Indexes** | 98+ |
| **Total Foreign Keys** | 120+ |
| **Database Size** | ~1.6 MB |
| **Tables with Optimistic Locking** | 40 |
| **Tables with Audit Fields** | 38 |
| **Junction Tables** | 8 |
| **Reference Tables** | 5 |

---

## Current Data Inventory

### Item Catalog
- **15 items** across 5 categories
- Categories: Food (4), Water (2), Hygiene (4), Medical (1), Shelter (4)

### Inventory
- **15 inventory records** at Kingston Central Depot
- Total usable: 10,195 units
- Total reserved: 325 units
- Total defective: 53 units
- Total expired: 58 units

### Reference Data
- **5 item categories** (FOOD, WATER, HYGIENE, MEDICAL, SHELTER)
- **5 units of measure** (UNIT, KG, LITRE, BOX, SACK)
- **14 Jamaican parishes**
- **1 warehouse** (Kingston Central Depot)
- **1 custodian** (ODPEM)

### User Accounts
- **4 users** with role-based access

---

## Schema Version History

### November 12, 2025
- Added `agency_account_request` and `agency_account_request_audit` tables
- Enhanced `user` table with full account management (MFA, lockout, password management)
- Added `agency.warehouse_id` with complex CHECK constraint
- Enabled optimistic locking on all 40 tables
- Added `citext` extension for case-insensitive email comparisons
- Created comprehensive test item catalog (15 items)
- Created test inventory data at Kingston Central Depot

### Previous
- Original AIDMGMT-3.1 schema with 40 core tables
- Removed Needs/Fulfillment workflow (7 tables dropped)

---

**End of Schema Documentation**
