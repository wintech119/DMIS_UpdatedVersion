# Disaster Relief Inventory Management System (DRIMS)
## Comprehensive Requirements Document for Replit Implementation

---

## 1. SYSTEM OVERVIEW

### 1.1 Purpose
A comprehensive disaster relief inventory management system designed for the Government of Jamaica's Office of Disaster Preparedness and Emergency Management (ODPEM) to track and manage relief supplies with location-based inventory tracking, role-based access control, and real-time analytics.

### 1.2 Technology Stack
- **Backend Framework**: Python 3.11, Flask 3.0.3
- **Database**: PostgreSQL 16 (Production), SQLite3 (Development)
- **ORM**: SQLAlchemy 2.0.32
- **Authentication**: Flask-Login with Werkzeug password hashing
- **Frontend**: Server-side rendered Jinja2 templates
- **UI Framework**: Bootstrap 5.3.3
- **Icons**: Bootstrap Icons 1.11.3
- **Data Processing**: Pandas 2.2.2
- **Additional Libraries**: python-dotenv, Gunicorn (production)

### 1.3 Core Modules Required
```
app.py (main application)
date_utils.py (datetime formatting utilities)
status_helpers.py (workflow status logic)
storage_service.py (file upload handling)
seed_data.py (database seeding)
```

---

## 2. DATABASE SCHEMA

### 2.0 Schema Integration Overview

This database schema is a hybrid integration of:
1. **aidmgmt-3.sql** - The authoritative disaster relief management schema from ODPEM
2. **DRIMS Extensions** - Additional tables for user management, authentication, and enhanced workflows

**Table Name Mapping:**

| DRIMS Concept | aidmgmt-3.sql Table | Notes |
|---------------|---------------------|-------|
| Location/Depot/Hub | `warehouse` | Warehouses and storage locations |
| Disaster Event | `event` | Disaster/emergency events |
| Needs List | `reliefrqst` | Relief requests from agencies |
| Needs List Item | `reliefrqst_item` | Line items in relief requests |
| Fulfilment/Package | `reliefpkg` | Relief packages prepared for dispatch |
| Fulfilment Line Item | `reliefpkg_item` | Items in relief packages |
| Receipt/Intake | `dbintake` | Distribution intake at receiving location |
| Receipt Item | `dbintake_item` | Items received at destination |
| Item | `item` | Relief supply items |
| Donor | `donor` | Donation sources |
| Agency | `agency` | Request-only locations (shelters, community centers) |
| Transfer | `transfer` | Stock transfers between warehouses |
| Storage Location | `location` | Physical locations within warehouses |
| Inventory | `inventory` | Stock levels by item and warehouse |

**DRIMS-Only Tables (not in aidmgmt-3.sql):**
- `user` - User authentication
- `role` - Role definitions
- `user_role` - User-role assignments
- `user_warehouse` - User-warehouse access control
- `notification` - In-app notifications
- `transfer_request` - Enhanced transfer workflow
- `transaction` - Legacy transaction log (for backward compatibility)

**Important Schema Notes:**
1. All aidmgmt-3.sql tables use audit fields: `create_by_id`, `create_dtime`, `update_by_id`, `update_dtime`, `version_nbr`
2. Status codes are typically CHAR(1) with specific meanings (see comments in each table)
3. Quantity fields are DECIMAL(12,2) to support fractional amounts
4. All names (warehouse, agency, donor, item, etc.) must be UPPERCASE for consistency
5. The `citext` extension is required for case-insensitive text in `item.item_desc`

**IMPORTANT**: This schema integrates tables from the original `aidmgmt-3.sql` database with DRIMS-specific extensions. Where tables exist in both systems, the aidmgmt-3.sql definition takes precedence.

### 2.1 Reference Tables (from aidmgmt-3.sql)

#### 2.1.1 Country Table
```sql
CREATE TABLE country (
    country_id SMALLINT NOT NULL PRIMARY KEY,
    country_name VARCHAR(80) NOT NULL
);
```

#### 2.1.2 Parish Table
```sql
CREATE TABLE parish (
    parish_code CHAR(2) NOT NULL PRIMARY KEY
        CHECK (parish_code SIMILAR TO '[0-9]*' AND parish_code::INTEGER BETWEEN 1 AND 14),
    parish_name VARCHAR(40) NOT NULL
);
```

#### 2.1.3 Unit of Measure Table
```sql
CREATE TABLE unitofmeasure (
    uom_code VARCHAR(25) NOT NULL PRIMARY KEY
        CHECK (uom_code = UPPER(uom_code)),
    uom_desc VARCHAR(60) NOT NULL,
    comments_text TEXT,
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    version_nbr INTEGER NOT NULL
);
```

#### 2.1.4 Item Category Table
```sql
CREATE TABLE itemcatg (
    category_code VARCHAR(30) NOT NULL PRIMARY KEY
        CHECK (category_code = UPPER(category_code)),
    category_desc VARCHAR(60) NOT NULL,
    comments_text TEXT,
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    version_nbr INTEGER NOT NULL
);
```

### 2.2 Core Entity Tables (from aidmgmt-3.sql)

#### 2.2.1 Event Table (replaces event)
```sql
CREATE TABLE event (
    event_id INTEGER NOT NULL GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    event_type VARCHAR(16) NOT NULL
        CHECK (event_type IN ('STORM','TORNADO','FLOOD','TSUNAMI','FIRE','EARTHQUAKE','WAR','EPIDEMIC')),
    start_date DATE NOT NULL
        CHECK (start_date <= CURRENT_DATE),
    event_name VARCHAR(60) NOT NULL,
    event_desc VARCHAR(255) NOT NULL,
    impact_desc TEXT NOT NULL,
    status_code CHAR(1) NOT NULL
        CHECK (status_code IN ('A','C')),  -- A=Active, C=Closed
    closed_date DATE
        CHECK ((status_code = 'A' AND closed_date IS NULL) 
            OR (status_code = 'C' AND closed_date IS NOT NULL)),
    reason_desc VARCHAR(255)
        CHECK ((reason_desc IS NULL AND closed_date IS NULL)
            OR (reason_desc IS NOT NULL AND closed_date IS NOT NULL)),
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    version_nbr INTEGER NOT NULL
);
```

#### 2.2.2 Donor Table
```sql
CREATE TABLE donor (
    donor_id INTEGER NOT NULL GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    donor_type CHAR(1) NOT NULL
        CHECK (donor_type IN ('I','O')),  -- I=Individual, O=Organization
    donor_name VARCHAR(255) NOT NULL
        CHECK (donor_name = UPPER(donor_name)) UNIQUE,
    org_type_desc VARCHAR(30),
    address1_text VARCHAR(255) NOT NULL,
    address2_text VARCHAR(255),
    country_id SMALLINT NOT NULL DEFAULT 388 REFERENCES country,
    phone_no VARCHAR(20) NOT NULL,
    email_text VARCHAR(100),
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    version_nbr INTEGER NOT NULL
);
```

#### 2.2.3 Custodian Table
```sql
CREATE TABLE custodian (
    custodian_id INTEGER NOT NULL GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    custodian_name VARCHAR(120) NOT NULL 
        DEFAULT 'OFFICE OF DISASTER PREPAREDNESS AND EMERGENCY MANAGEMENT (ODPEM)'
        CHECK (custodian_name = UPPER(custodian_name)) UNIQUE,
    address1_text VARCHAR(255) NOT NULL,
    address2_text VARCHAR(255),
    parish_code CHAR(2) NOT NULL REFERENCES parish,
    contact_name VARCHAR(50) NOT NULL
        CHECK (contact_name = UPPER(contact_name)),
    phone_no VARCHAR(20) NOT NULL,
    email_text VARCHAR(100),
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    version_nbr INTEGER NOT NULL
);
```

#### 2.2.4 Item Table
```sql
CREATE TABLE item (
    item_id INTEGER NOT NULL GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    item_name VARCHAR(60) NOT NULL
        CHECK (item_name = UPPER(item_name)) UNIQUE,
    sku_code VARCHAR(30) NOT NULL
        CHECK (sku_code = UPPER(sku_code)) UNIQUE,
    category_code VARCHAR(30) NOT NULL REFERENCES itemcatg,
    item_desc CITEXT NOT NULL,
    reorder_qty DECIMAL(12,2) NOT NULL
        CHECK (reorder_qty > 0.00),
    default_uom_code VARCHAR(25) NOT NULL REFERENCES unitofmeasure,
    usage_desc TEXT,
    storage_desc TEXT,
    expiration_apply_flag BOOLEAN NOT NULL,
    comments_text TEXT,
    status_code CHAR(1) NOT NULL
        CHECK (status_code IN ('A','I')),  -- A=Active, I=Inactive
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    version_nbr INTEGER NOT NULL
);
CREATE INDEX dk_item_1 ON item(item_desc);
```

#### 2.2.5 Warehouse Table (replaces location/Depot)
```sql
CREATE TABLE warehouse (
    warehouse_id INTEGER NOT NULL GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    warehouse_name TEXT NOT NULL,
    warehouse_type VARCHAR(10) NOT NULL
        CHECK (warehouse_type IN ('MAIN','HUB','SUB-HUB','AGENCY')),
    address1_text VARCHAR(255) NOT NULL,
    address2_text VARCHAR(255),
    parish_code CHAR(2) NOT NULL REFERENCES parish,
    contact_name VARCHAR(50) NOT NULL
        CHECK (contact_name = UPPER(contact_name)),
    phone_no VARCHAR(20) NOT NULL,
    email_text VARCHAR(100),
    custodian_id INTEGER NOT NULL REFERENCES custodian,
    status_code CHAR(1) NOT NULL
        CHECK (status_code IN ('A','I')),  -- A=Active, I=Inactive
    reason_desc VARCHAR(255)
        CHECK ((reason_desc IS NULL AND status_code = 'A')
            OR (reason_desc IS NOT NULL AND status_code = 'I')),
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    version_nbr INTEGER NOT NULL
);
```

#### 2.2.6 Agency Table
```sql
CREATE TABLE agency (
    agency_id INTEGER NOT NULL GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    agency_name VARCHAR(120) NOT NULL
        CHECK (agency_name = UPPER(agency_name)) UNIQUE,
    address1_text VARCHAR(255) NOT NULL,
    address2_text VARCHAR(255),
    parish_code CHAR(2) NOT NULL REFERENCES parish,
    contact_name VARCHAR(50) NOT NULL
        CHECK (contact_name = UPPER(contact_name)),
    phone_no VARCHAR(20) NOT NULL,
    email_text VARCHAR(100),
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    version_nbr INTEGER NOT NULL
);
```

### 2.3 Inventory Management (from aidmgmt-3.sql)

#### 2.3.1 Inventory Table
```sql
CREATE TABLE inventory (
    inventory_id INTEGER NOT NULL GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    warehouse_id INTEGER NOT NULL REFERENCES warehouse,
    item_id INTEGER NOT NULL REFERENCES item,
    usable_qty DECIMAL(12,2) NOT NULL CHECK (usable_qty >= 0.00),
    reserved_qty DECIMAL(12,2) NOT NULL CHECK (reserved_qty <= usable_qty),
    defective_qty DECIMAL(12,2) NOT NULL CHECK (defective_qty >= 0.00),
    expired_qty DECIMAL(12,2) NOT NULL CHECK (expired_qty >= 0.00),
    uom_code VARCHAR(25) NOT NULL REFERENCES unitofmeasure,
    last_verified_by VARCHAR(20),
    last_verified_date DATE
        CHECK ((last_verified_by IS NULL AND last_verified_date IS NULL)
            OR (last_verified_by IS NOT NULL AND last_verified_date IS NOT NULL)),
    status_code CHAR(1) NOT NULL
        CHECK (status_code IN ('A','U')),  -- A=Available, U=Unavailable
    comments_text TEXT,
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    version_nbr INTEGER NOT NULL
);
CREATE UNIQUE INDEX uk_inventory_1 ON inventory(item_id, inventory_id);
CREATE INDEX dk_inventory_1 ON inventory(warehouse_id);
CREATE UNIQUE INDEX uk_inventory_2 ON inventory(item_id) WHERE usable_qty > 0.00;
```

#### 2.3.2 Location Table (storage locations within warehouses)
```sql
CREATE TABLE location (
    location_id INTEGER NOT NULL GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    inventory_id INTEGER NOT NULL REFERENCES inventory,
    location_desc VARCHAR(255) NOT NULL,
    status_code CHAR(1) NOT NULL
        CHECK (status_code IN ('O','C')),  -- O=Open, C=Closed
    comments_text VARCHAR(255),
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    version_nbr INTEGER NOT NULL
);
CREATE INDEX dk_location_1 ON location(inventory_id);
```

#### 2.3.3 Item Location Table
```sql
CREATE TABLE item_location (
    inventory_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    location_id INTEGER NOT NULL REFERENCES location,
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    FOREIGN KEY (item_id, inventory_id) REFERENCES inventory(item_id, inventory_id),
    PRIMARY KEY (item_id, location_id)
);
CREATE INDEX dk_item_location_1 ON item_location(inventory_id, location_id);
```

### 2.4 Donation Management (from aidmgmt-3.sql)

#### 2.4.1 Donation Table
```sql
CREATE TABLE donation (
    donation_id INTEGER NOT NULL GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    donor_id INTEGER NOT NULL REFERENCES donor,
    donation_desc TEXT NOT NULL,
    event_id INTEGER NOT NULL REFERENCES event,
    custodian_id INTEGER NOT NULL REFERENCES custodian,
    received_date DATE NOT NULL CHECK (received_date <= CURRENT_DATE),
    status_code CHAR(1) NOT NULL
        CHECK (status_code IN ('E','V')),  -- E=Entered, V=Verified
    comments_text TEXT,
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    verify_by_id VARCHAR(20) NOT NULL,
    verify_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    version_nbr INTEGER NOT NULL
);
```

#### 2.4.2 Donation Item Table
```sql
CREATE TABLE donation_item (
    donation_id INTEGER NOT NULL REFERENCES donation,
    item_id INTEGER NOT NULL REFERENCES item,
    item_qty DECIMAL(12,2) NOT NULL CHECK (item_qty >= 0.00),
    uom_code VARCHAR(25) NOT NULL REFERENCES unitofmeasure,
    location_name TEXT NOT NULL,
    status_code CHAR(1) NOT NULL
        CHECK (status_code IN ('P','V')),  -- P=Pending verification, V=Verified
    comments_text TEXT,
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    verify_by_id VARCHAR(20) NOT NULL,
    verify_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    version_nbr INTEGER NOT NULL,
    PRIMARY KEY (donation_id, item_id)
);
```

#### 2.4.3 Donation Intake Table
```sql
CREATE TABLE dnintake (
    donation_id INTEGER NOT NULL REFERENCES donation,
    inventory_id INTEGER NOT NULL REFERENCES inventory,
    intake_date DATE NOT NULL CHECK (intake_date <= CURRENT_DATE),
    comments_text VARCHAR(255),
    status_code CHAR(1) NOT NULL
        CHECK (status_code IN ('I','C','V')),  -- I=Incomplete, C=Completed, V=Verified
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    verify_by_id VARCHAR(20) NOT NULL,
    verify_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    version_nbr INTEGER NOT NULL,
    PRIMARY KEY (donation_id, inventory_id)
);
```

#### 2.4.4 Donation Intake Item Table
```sql
CREATE TABLE dnintake_item (
    donation_id INTEGER NOT NULL,
    inventory_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    usable_qty DECIMAL(12,2) NOT NULL CHECK (usable_qty >= 0.00),
    location1_id INTEGER REFERENCES location,
    defective_qty DECIMAL(12,2) NOT NULL CHECK (defective_qty >= 0.00),
    location2_id INTEGER REFERENCES location,
    expired_qty DECIMAL(12,2) NOT NULL CHECK (expired_qty >= 0.00),
    location3_id INTEGER REFERENCES location,
    uom_code VARCHAR(25) NOT NULL REFERENCES unitofmeasure,
    status_code CHAR(1) NOT NULL
        CHECK (status_code IN ('P','V')),  -- P=Pending verification, V=Verified
    comments_text VARCHAR(255),
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    version_nbr INTEGER NOT NULL,
    FOREIGN KEY (donation_id, inventory_id) REFERENCES dnintake(donation_id, inventory_id),
    PRIMARY KEY (donation_id, inventory_id, item_id)
);
CREATE INDEX dk_dnintake_item_1 ON dnintake_item(inventory_id, item_id);
CREATE INDEX dk_dnintake_item_2 ON dnintake_item(item_id);
```

### 2.5 Transfer Management (from aidmgmt-3.sql)

#### 2.5.1 Transfer Table
```sql
CREATE TABLE transfer (
    transfer_id INTEGER NOT NULL GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    fr_inventory_id INTEGER NOT NULL REFERENCES inventory,
    to_inventory_id INTEGER NOT NULL REFERENCES inventory,
    transfer_date DATE NOT NULL CHECK (transfer_date <= CURRENT_DATE),
    transport_mode VARCHAR(255),
    comments_text VARCHAR(255),
    status_code CHAR(1) NOT NULL
        CHECK (status_code IN ('P','C','V','D')),  
        -- P=Processing, C=Completed, V=Verified, D=Dispatched
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    verify_by_id VARCHAR(20) NOT NULL,
    verify_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    version_nbr INTEGER NOT NULL
);
CREATE INDEX dk_transfer_1 ON transfer(transfer_date);
CREATE INDEX dk_transfer_2 ON transfer(fr_inventory_id);
CREATE INDEX dk_transfer_3 ON transfer(to_inventory_id);
```

#### 2.5.2 Transfer Item Table
```sql
CREATE TABLE transfer_item (
    transfer_id INTEGER NOT NULL REFERENCES transfer,
    item_id INTEGER NOT NULL,
    item_qty DECIMAL(12,2) NOT NULL CHECK (item_qty >= 0.00),
    uom_code VARCHAR(25) NOT NULL REFERENCES unitofmeasure,
    reason_text VARCHAR(255),
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    version_nbr INTEGER NOT NULL,
    PRIMARY KEY (transfer_id, item_id)
);
CREATE INDEX dk_transfer_item_1 ON transfer_item(item_id);
```

### 2.6 Relief Request Management (from aidmgmt-3.sql)

#### 2.6.1 Relief Request Table (replaces needs_list)
```sql
CREATE TABLE reliefrqst (
    reliefrqst_id INTEGER NOT NULL GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    agency_id INTEGER NOT NULL REFERENCES agency,
    request_date DATE NOT NULL CHECK (request_date <= CURRENT_DATE),
    urgency_ind CHAR(1) NOT NULL
        CHECK (urgency_ind IN ('L','M','H','C')),  -- L=Low, M=Medium, H=High, C=Critical
    status_code SMALLINT NOT NULL
        CHECK (status_code BETWEEN 0 AND 7),
        -- 0=Draft, 1=Awaiting approval, 2=Cancelled, 3=Submitted,
        -- 4=Denied, 5=Part filled, 6=Closed, 7=Filled
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    review_by_id VARCHAR(20)
        CHECK ((review_by_id IS NULL AND status_code < 2)
            OR (review_by_id IS NOT NULL AND status_code >= 2)),
    review_dtime TIMESTAMP(0) WITHOUT TIME ZONE
        CHECK ((review_by_id IS NULL AND review_dtime IS NULL)
            OR (review_by_id IS NOT NULL AND review_dtime IS NOT NULL)),
    action_by_id VARCHAR(20)
        CHECK ((action_by_id IS NULL AND status_code < 4)
            OR (action_by_id IS NOT NULL AND status_code >= 4)),
    action_dtime TIMESTAMP(0) WITHOUT TIME ZONE
        CHECK ((action_by_id IS NULL AND action_dtime IS NULL)
            OR (action_by_id IS NOT NULL AND action_dtime IS NOT NULL)),
    version_nbr INTEGER NOT NULL
);
CREATE INDEX dk_reliefrqst_1 ON reliefrqst(agency_id, request_date);
CREATE INDEX dk_reliefrqst_2 ON reliefrqst(request_date, status_code);
CREATE INDEX dk_reliefrqst_3 ON reliefrqst(status_code, urgency_ind);
```

#### 2.6.2 Relief Request Item Table
```sql
CREATE TABLE reliefrqst_item (
    reliefrqst_id INTEGER NOT NULL REFERENCES reliefrqst,
    item_id INTEGER NOT NULL REFERENCES item,
    request_qty DECIMAL(12,2) NOT NULL CHECK (request_qty > 0.00),
    issue_qty DECIMAL(12,2) NOT NULL CHECK (issue_qty <= request_qty),
    urgency_ind CHAR(1) NOT NULL
        CHECK (urgency_ind IN ('L','M','H','C')),
    rqst_reason_desc VARCHAR(255)
        CHECK ((rqst_reason_desc IS NOT NULL)
            OR (rqst_reason_desc IS NULL AND urgency_ind IN ('L','M'))),
    required_by_date DATE
        CHECK ((required_by_date IS NOT NULL)
            OR (required_by_date IS NULL AND urgency_ind IN ('L','M'))),
    status_code CHAR(1) NOT NULL
        CHECK (status_code IN ('R','U','W','D','P','L','F')),
        -- R=Requested, U=Unavailable, W=Waiting availability,
        -- D=Denied, P=Partly filled, L=Limit allowed, F=Filled
    status_reason_desc VARCHAR(255),
    action_by_id VARCHAR(20)
        CHECK ((action_by_id IS NULL AND status_code = 'R') 
            OR (action_by_id IS NOT NULL AND status_code != 'R')),
    action_dtime TIMESTAMP(0) WITHOUT TIME ZONE
        CHECK ((action_by_id IS NULL AND action_dtime IS NULL) 
            OR (action_by_id IS NOT NULL AND action_dtime IS NOT NULL)),
    version_nbr INTEGER NOT NULL
);
```

#### 2.6.3 Relief Package Table (replaces fulfilment)
```sql
CREATE TABLE reliefpkg (
    reliefpkg_id INTEGER NOT NULL GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    to_inventory_id INTEGER NOT NULL REFERENCES inventory,
    reliefrqst_id INTEGER NOT NULL REFERENCES reliefrqst,
    start_date DATE NOT NULL DEFAULT CURRENT_DATE CHECK (start_date <= CURRENT_DATE),
    dispatch_dtime TIMESTAMP(0) WITHOUT TIME ZONE
        CHECK ((dispatch_dtime IS NULL AND status_code != 'D')
            OR (dispatch_dtime IS NOT NULL AND status_code = 'D')),
    transport_mode VARCHAR(255),
    comments_text VARCHAR(255),
    status_code CHAR(1) NOT NULL
        CHECK (status_code IN ('P','C','V','D')),
        -- P=Processing, C=Completed, V=Verified, D=Dispatched
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE,
    verify_by_id VARCHAR(20) NOT NULL,
    verify_dtime TIMESTAMP(0) WITHOUT TIME ZONE,
    version_nbr INTEGER NOT NULL
);
CREATE INDEX dk_reliefpkg_1 ON reliefpkg(start_date);
CREATE INDEX dk_reliefpkg_3 ON reliefpkg(to_inventory_id);
```

#### 2.6.4 Relief Package Item Table
```sql
CREATE TABLE reliefpkg_item (
    reliefpkg_id INTEGER NOT NULL REFERENCES reliefpkg,
    fr_inventory_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    item_qty DECIMAL(12,2) NOT NULL CHECK (item_qty >= 0.00),
    uom_code VARCHAR(25) NOT NULL REFERENCES unitofmeasure,
    reason_text VARCHAR(255),
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    version_nbr INTEGER NOT NULL,
    FOREIGN KEY (item_id, fr_inventory_id) REFERENCES inventory(item_id, inventory_id),
    PRIMARY KEY (reliefpkg_id, fr_inventory_id, item_id)
);
CREATE INDEX dk_reliefpkg_item_1 ON reliefpkg_item(fr_inventory_id, item_id);
CREATE INDEX dk_reliefpkg_item_2 ON reliefpkg_item(item_id);
```

#### 2.6.5 Distribution Intake Table
```sql
CREATE TABLE dbintake (
    reliefpkg_id INTEGER NOT NULL REFERENCES reliefpkg,
    inventory_id INTEGER NOT NULL REFERENCES inventory,
    intake_date DATE NOT NULL CHECK (intake_date <= CURRENT_DATE),
    comments_text VARCHAR(255),
    status_code CHAR(1) NOT NULL
        CHECK (status_code IN ('I','C','V')),  -- I=Incomplete, C=Completed, V=Verified
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE,
    verify_by_id VARCHAR(20) NOT NULL,
    verify_dtime TIMESTAMP(0) WITHOUT TIME ZONE,
    version_nbr INTEGER NOT NULL,
    PRIMARY KEY (reliefpkg_id, inventory_id)
);
```

#### 2.6.6 Distribution Intake Item Table
```sql
CREATE TABLE dbintake_item (
    reliefpkg_id INTEGER NOT NULL,
    inventory_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    usable_qty DECIMAL(12,2) NOT NULL CHECK (usable_qty >= 0.00),
    location1_id INTEGER REFERENCES location,
    defective_qty DECIMAL(12,2) NOT NULL CHECK (defective_qty >= 0.00),
    location2_id INTEGER REFERENCES location,
    expired_qty DECIMAL(12,2) NOT NULL CHECK (expired_qty >= 0.00),
    location3_id INTEGER REFERENCES location,
    uom_code VARCHAR(25) NOT NULL REFERENCES unitofmeasure,
    status_code CHAR(1) NOT NULL
        CHECK (status_code IN ('P','V')),  -- P=Pending verification, V=Verified
    comments_text VARCHAR(255),
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    version_nbr INTEGER NOT NULL,
    FOREIGN KEY (reliefpkg_id, inventory_id) REFERENCES dbintake(reliefpkg_id, inventory_id),
    PRIMARY KEY (reliefpkg_id, inventory_id, item_id)
);
CREATE INDEX dk_dbintake_item_1 ON dbintake_item(inventory_id, item_id);
CREATE INDEX dk_dbintake_item_2 ON dbintake_item(item_id);
```

### 2.7 DRIMS Extension Tables (not in aidmgmt-3.sql)

These tables extend the aidmgmt-3.sql schema with DRIMS-specific functionality for user management, notifications, and enhanced workflows. These tables implement the modern DRIMS workflow that runs alongside the aidmgmt-3.sql relief request system.

**Important:** The DRIMS application can use EITHER the aidmgmt-3.sql workflow (`reliefrqst` → `reliefpkg`) OR the DRIMS workflow (`needs_list` → `fulfilment`) depending on configuration. Both are included for flexibility.

#### 2.7.1 DRIMS Needs List Workflow (Enhanced Modern Workflow)

**Table: needs_list**
```sql
CREATE TABLE needs_list (
    id SERIAL PRIMARY KEY,
    list_number VARCHAR(64) UNIQUE NOT NULL,  -- e.g., NL-000001
    agency_id INTEGER NOT NULL REFERENCES agency(agency_id),
    event_id INTEGER NOT NULL REFERENCES event(event_id),
    submission_type VARCHAR(20) DEFAULT 'DRAFT' NOT NULL,  -- DRAFT, NEEDS, FORMAL_REQUEST
    requested_by_name VARCHAR(200),
    requested_by_contact VARCHAR(200),
    priority VARCHAR(20) DEFAULT 'MEDIUM' NOT NULL,  -- LOW, MEDIUM, HIGH, CRITICAL
    urgency VARCHAR(20) DEFAULT 'ROUTINE',  -- ROUTINE, URGENT, EMERGENCY
    status VARCHAR(50) DEFAULT 'Draft' NOT NULL,
    -- Draft, Submitted, Under Review, Approved, In Preparation, 
    -- Dispatched, Received, Completed, Rejected, Cancelled
    is_draft BOOLEAN DEFAULT TRUE NOT NULL,
    is_locked BOOLEAN DEFAULT FALSE NOT NULL,
    locked_by VARCHAR(200),
    locked_at TIMESTAMP,
    notes TEXT,
    justification TEXT,
    review_notes TEXT,
    created_by VARCHAR(200) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    submitted_at TIMESTAMP,
    reviewed_by VARCHAR(200),
    reviewed_at TIMESTAMP,
    approved_by VARCHAR(200),
    approved_at TIMESTAMP
);
CREATE INDEX idx_needs_list_agency ON needs_list(agency_id);
CREATE INDEX idx_needs_list_status ON needs_list(status);
CREATE INDEX idx_needs_list_number ON needs_list(list_number);
CREATE INDEX idx_needs_list_event ON needs_list(event_id);
```

**Table: needs_list_item**
```sql
CREATE TABLE needs_list_item (
    id SERIAL PRIMARY KEY,
    needs_list_id INTEGER NOT NULL REFERENCES needs_list(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES item(item_id),
    requested_qty DECIMAL(12,2) NOT NULL,
    approved_qty DECIMAL(12,2) DEFAULT 0 NOT NULL,
    fulfilled_qty DECIMAL(12,2) DEFAULT 0 NOT NULL,
    notes TEXT,
    justification TEXT,
    status VARCHAR(50) DEFAULT 'Pending',
    -- Pending, Approved, Partially Approved, Rejected, 
    -- In Preparation, Dispatched, Received
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);
CREATE INDEX idx_needs_list_item_list ON needs_list_item(needs_list_id);
CREATE INDEX idx_needs_list_item_item ON needs_list_item(item_id);
```

#### 2.7.2 DRIMS Fulfilment Workflow

**Table: fulfilment**
```sql
CREATE TABLE fulfilment (
    id SERIAL PRIMARY KEY,
    needs_list_id INTEGER NOT NULL REFERENCES needs_list(id),
    fulfilment_number VARCHAR(64) UNIQUE NOT NULL,  -- e.g., FUL-000001
    status VARCHAR(50) DEFAULT 'In Preparation' NOT NULL,
    -- In Preparation, Ready for Dispatch, Dispatched, 
    -- Received, Completed, Cancelled
    is_partial BOOLEAN DEFAULT FALSE NOT NULL,
    notes TEXT,
    prepared_by VARCHAR(200),
    prepared_at TIMESTAMP,
    dispatched_by VARCHAR(200),
    dispatched_at TIMESTAMP,
    received_by VARCHAR(200),
    received_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);
CREATE INDEX idx_fulfilment_needs_list ON fulfilment(needs_list_id);
CREATE INDEX idx_fulfilment_number ON fulfilment(fulfilment_number);
CREATE INDEX idx_fulfilment_status ON fulfilment(status);
```

**Table: fulfilment_line_item**
```sql
CREATE TABLE fulfilment_line_item (
    id SERIAL PRIMARY KEY,
    fulfilment_id INTEGER NOT NULL REFERENCES fulfilment(id) ON DELETE CASCADE,
    source_warehouse_id INTEGER NOT NULL REFERENCES warehouse(warehouse_id),
    item_id INTEGER NOT NULL REFERENCES item(item_id),
    allocated_qty DECIMAL(12,2) NOT NULL,
    dispatched_qty DECIMAL(12,2) DEFAULT 0 NOT NULL,
    received_qty DECIMAL(12,2) DEFAULT 0 NOT NULL,
    notes TEXT,
    status VARCHAR(50) DEFAULT 'Allocated',
    -- Allocated, Dispatched, Received, Short, Damaged
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);
CREATE INDEX idx_fulfilment_line_item_fulfilment ON fulfilment_line_item(fulfilment_id);
CREATE INDEX idx_fulfilment_line_item_warehouse ON fulfilment_line_item(source_warehouse_id);
CREATE INDEX idx_fulfilment_line_item_item ON fulfilment_line_item(item_id);
```

**Table: fulfilment_edit_log**
```sql
CREATE TABLE fulfilment_edit_log (
    id SERIAL PRIMARY KEY,
    fulfilment_id INTEGER NOT NULL REFERENCES fulfilment(id),
    line_item_id INTEGER REFERENCES fulfilment_line_item(id),
    field_changed VARCHAR(100) NOT NULL,
    old_value TEXT,
    new_value TEXT,
    reason TEXT,
    changed_by VARCHAR(200) NOT NULL,
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);
CREATE INDEX idx_fulfilment_edit_log_fulfilment ON fulfilment_edit_log(fulfilment_id);
```

#### 2.7.3 DRIMS Dispatch & Receipt

**Table: dispatch_manifest**
```sql
CREATE TABLE dispatch_manifest (
    id SERIAL PRIMARY KEY,
    fulfilment_id INTEGER NOT NULL REFERENCES fulfilment(id),
    manifest_number VARCHAR(64) UNIQUE NOT NULL,  -- e.g., DSP-000001
    from_warehouse_id INTEGER NOT NULL REFERENCES warehouse(warehouse_id),
    to_warehouse_id INTEGER NOT NULL REFERENCES warehouse(warehouse_id),
    vehicle_info VARCHAR(200),
    driver_name VARCHAR(200),
    driver_contact VARCHAR(100),
    dispatch_notes TEXT,
    dispatched_by VARCHAR(200) NOT NULL,
    dispatched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);
CREATE INDEX idx_dispatch_manifest_fulfilment ON dispatch_manifest(fulfilment_id);
CREATE INDEX idx_dispatch_manifest_from ON dispatch_manifest(from_warehouse_id);
CREATE INDEX idx_dispatch_manifest_to ON dispatch_manifest(to_warehouse_id);
```

**Table: receipt_record**
```sql
CREATE TABLE receipt_record (
    id SERIAL PRIMARY KEY,
    fulfilment_id INTEGER NOT NULL REFERENCES fulfilment(id),
    receipt_number VARCHAR(64) UNIQUE NOT NULL,  -- e.g., RCP-000001
    received_by VARCHAR(200) NOT NULL,
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    condition_notes TEXT,
    discrepancy_notes TEXT,
    signature_path VARCHAR(500)
);
CREATE INDEX idx_receipt_record_fulfilment ON receipt_record(fulfilment_id);
```

#### 2.7.4 DRIMS Distribution Package (Alternative Workflow)

**Table: distribution_package**
```sql
CREATE TABLE distribution_package (
    id SERIAL PRIMARY KEY,
    package_number VARCHAR(64) UNIQUE NOT NULL,
    recipient_agency_id INTEGER NOT NULL REFERENCES agency(agency_id),
    assigned_warehouse_id INTEGER REFERENCES warehouse(warehouse_id),
    event_id INTEGER REFERENCES event(event_id),
    status VARCHAR(50) DEFAULT 'Draft' NOT NULL,
    is_partial BOOLEAN DEFAULT FALSE NOT NULL,
    created_by VARCHAR(200) NOT NULL,
    approved_by VARCHAR(200),
    approved_at TIMESTAMP,
    dispatched_by VARCHAR(200),
    dispatched_at TIMESTAMP,
    delivered_at TIMESTAMP,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);
CREATE INDEX idx_distribution_package_agency ON distribution_package(recipient_agency_id);
CREATE INDEX idx_distribution_package_warehouse ON distribution_package(assigned_warehouse_id);
CREATE INDEX idx_distribution_package_event ON distribution_package(event_id);
```

**Table: distribution_package_item**
```sql
CREATE TABLE distribution_package_item (
    id SERIAL PRIMARY KEY,
    package_id INTEGER NOT NULL REFERENCES distribution_package(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES item(item_id),
    quantity DECIMAL(12,2) NOT NULL,
    notes TEXT
);
CREATE INDEX idx_distribution_package_item_package ON distribution_package_item(package_id);
CREATE INDEX idx_distribution_package_item_item ON distribution_package_item(item_id);
```

#### 2.7.5 User Authentication & Authorization

**Table: user**
```sql
CREATE TABLE user (
    id SERIAL PRIMARY KEY,
    email VARCHAR(200) UNIQUE NOT NULL,
    password_hash VARCHAR(256) NOT NULL,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    full_name VARCHAR(200),  -- Legacy field
    role VARCHAR(50),  -- Legacy field for backward compatibility
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    organization VARCHAR(200),
    job_title VARCHAR(200),
    phone VARCHAR(50),
    timezone VARCHAR(50) DEFAULT 'America/Jamaica' NOT NULL,
    language VARCHAR(10) DEFAULT 'en' NOT NULL,
    notification_preferences TEXT,
    assigned_warehouse_id INTEGER REFERENCES warehouse(warehouse_id),
    last_login_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_by_id INTEGER REFERENCES user(id),
    updated_by_id INTEGER REFERENCES user(id)
);
CREATE INDEX idx_user_email ON user(email);
```

**Table: role**
```sql
CREATE TABLE role (
    id SERIAL PRIMARY KEY,
    code VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);
CREATE INDEX idx_role_code ON role(code);
```

**Table: user_role** (Many-to-many)
```sql
CREATE TABLE user_role (
    user_id INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
    role_id INTEGER NOT NULL REFERENCES role(id) ON DELETE CASCADE,
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    assigned_by INTEGER REFERENCES user(id),
    PRIMARY KEY (user_id, role_id)
);
```

**Table: user_warehouse** (Many-to-many for warehouse access scoping)
```sql
CREATE TABLE user_warehouse (
    user_id INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
    warehouse_id INTEGER NOT NULL REFERENCES warehouse(warehouse_id) ON DELETE CASCADE,
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    assigned_by INTEGER REFERENCES user(id),
    PRIMARY KEY (user_id, warehouse_id)
);
```

#### 2.7.6 Notification System

**Table: notification**
```sql
CREATE TABLE notification (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES user(id),
    warehouse_id INTEGER REFERENCES warehouse(warehouse_id),
    reliefrqst_id INTEGER REFERENCES reliefrqst(reliefrqst_id),
    title VARCHAR(200) NOT NULL,
    message TEXT NOT NULL,
    type VARCHAR(50) NOT NULL,  -- submitted, approved, dispatched, received, comment
    status VARCHAR(20) DEFAULT 'unread' NOT NULL,  -- unread, read, archived
    link_url VARCHAR(500),
    payload TEXT,  -- JSON
    is_archived BOOLEAN DEFAULT FALSE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);
CREATE INDEX idx_notification_user_status ON notification(user_id, status, created_at);
CREATE INDEX idx_notification_warehouse ON notification(warehouse_id, created_at);
```

#### 2.7.7 Enhanced Transfer Request (DRIMS extension)

**Table: transfer_request**
```sql
CREATE TABLE transfer_request (
    id SERIAL PRIMARY KEY,
    from_warehouse_id INTEGER NOT NULL REFERENCES warehouse(warehouse_id),
    to_warehouse_id INTEGER NOT NULL REFERENCES warehouse(warehouse_id),
    item_id INTEGER NOT NULL REFERENCES item(item_id),
    quantity DECIMAL(12,2) NOT NULL,
    status VARCHAR(20) DEFAULT 'PENDING' NOT NULL,
    -- PENDING, APPROVED, REJECTED, COMPLETED
    requested_by INTEGER REFERENCES user(id),
    requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    reviewed_by INTEGER REFERENCES user(id),
    reviewed_at TIMESTAMP,
    notes TEXT
);
```

#### 2.7.8 Legacy Transaction Table (for backward compatibility)

**Table: transaction**
```sql
CREATE TABLE transaction (
    id SERIAL PRIMARY KEY,
    item_id INTEGER REFERENCES item(item_id),
    ttype VARCHAR(8) NOT NULL,  -- 'IN' or 'OUT'
    qty DECIMAL(12,2) NOT NULL,
    warehouse_id INTEGER REFERENCES warehouse(warehouse_id),
    donor_id INTEGER REFERENCES donor(donor_id),
    event_id INTEGER REFERENCES event(event_id),
    expiry_date DATE,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(200)
);
```

### 2.8 Database Initialization

### 2.8 Database Initialization

**Seed Data - Parishes (Jamaica)**
```sql
INSERT INTO parish (parish_code, parish_name) VALUES
('01', 'Kingston'),
('02', 'St. Andrew'),
('03', 'St. Thomas'),
('04', 'Portland'),
('05', 'St. Mary'),
('06', 'St. Ann'),
('07', 'Trelawny'),
('08', 'St. James'),
('09', 'Hanover'),
('10', 'Westmoreland'),
('11', 'St. Elizabeth'),
('12', 'Manchester'),
('13', 'Clarendon'),
('14', 'St. Catherine');
```

**Seed Data - Unit of Measure**
```sql
INSERT INTO unitofmeasure (uom_code, uom_desc, create_by_id, create_dtime, update_by_id, update_dtime, version_nbr) VALUES
('UNIT', 'Individual units', 'SYSTEM', CURRENT_TIMESTAMP, 'SYSTEM', CURRENT_TIMESTAMP, 1),
('KG', 'Kilograms', 'SYSTEM', CURRENT_TIMESTAMP, 'SYSTEM', CURRENT_TIMESTAMP, 1),
('LITRE', 'Litres', 'SYSTEM', CURRENT_TIMESTAMP, 'SYSTEM', CURRENT_TIMESTAMP, 1),
('BOX', 'Boxes', 'SYSTEM', CURRENT_TIMESTAMP, 'SYSTEM', CURRENT_TIMESTAMP, 1),
('SACK', 'Sacks', 'SYSTEM', CURRENT_TIMESTAMP, 'SYSTEM', CURRENT_TIMESTAMP, 1),
('BOTTLE', 'Bottles', 'SYSTEM', CURRENT_TIMESTAMP, 'SYSTEM', CURRENT_TIMESTAMP, 1),
('GALLON', 'Gallons', 'SYSTEM', CURRENT_TIMESTAMP, 'SYSTEM', CURRENT_TIMESTAMP, 1),
('METRE', 'Metres', 'SYSTEM', CURRENT_TIMESTAMP, 'SYSTEM', CURRENT_TIMESTAMP, 1),
('SHEET', 'Sheets', 'SYSTEM', CURRENT_TIMESTAMP, 'SYSTEM', CURRENT_TIMESTAMP, 1);
```

**Seed Data - Item Categories**
```sql
INSERT INTO itemcatg (category_code, category_desc, create_by_id, create_dtime, update_by_id, update_dtime, version_nbr) VALUES
('FOOD', 'Food Items', 'SYSTEM', CURRENT_TIMESTAMP, 'SYSTEM', CURRENT_TIMESTAMP, 1),
('WATER', 'Water and Beverages', 'SYSTEM', CURRENT_TIMESTAMP, 'SYSTEM', CURRENT_TIMESTAMP, 1),
('HYGIENE', 'Hygiene Products', 'SYSTEM', CURRENT_TIMESTAMP, 'SYSTEM', CURRENT_TIMESTAMP, 1),
('MEDICAL', 'Medical Supplies', 'SYSTEM', CURRENT_TIMESTAMP, 'SYSTEM', CURRENT_TIMESTAMP, 1),
('SHELTER', 'Shelter Materials', 'SYSTEM', CURRENT_TIMESTAMP, 'SYSTEM', CURRENT_TIMESTAMP, 1),
('CLOTHING', 'Clothing and Bedding', 'SYSTEM', CURRENT_TIMESTAMP, 'SYSTEM', CURRENT_TIMESTAMP, 1),
('CONSTRUCTION', 'Construction Materials', 'SYSTEM', CURRENT_TIMESTAMP, 'SYSTEM', CURRENT_TIMESTAMP, 1),
('TOOLS', 'Tools and Equipment', 'SYSTEM', CURRENT_TIMESTAMP, 'SYSTEM', CURRENT_TIMESTAMP, 1),
('OTHER', 'Other Items', 'SYSTEM', CURRENT_TIMESTAMP, 'SYSTEM', CURRENT_TIMESTAMP, 1);
```

**Seed Data - Custodian (ODPEM)**
```sql
INSERT INTO custodian (custodian_name, address1_text, parish_code, contact_name, phone_no, email_text, 
    create_by_id, create_dtime, update_by_id, update_dtime, version_nbr) VALUES
('OFFICE OF DISASTER PREPAREDNESS AND EMERGENCY MANAGEMENT (ODPEM)', 
 '2 Haining Road', '01', 'DIRECTOR GENERAL', '876-928-5111', 'info@odpem.gov.jm',
 'SYSTEM', CURRENT_TIMESTAMP, 'SYSTEM', CURRENT_TIMESTAMP, 1);
```

**Seed Data - Roles**
```sql
INSERT INTO role (code, name, description) VALUES
('SYSTEM_ADMINISTRATOR', 'System Administrator', 'Full system access and configuration'),
('LOGISTICS_MANAGER', 'Logistics Manager', 'Oversees all logistics operations'),
('LOGISTICS_OFFICER', 'Logistics Officer', 'Manages inventory and fulfillment'),
('MAIN_HUB_WAREHOUSE', 'Main Hub Warehouse', 'Main warehouse operations'),
('SUB_HUB_WAREHOUSE', 'Sub Hub Warehouse', 'Sub-hub warehouse operations'),
('AGENCY_HUB', 'Agency Hub', 'Agency requests and receipts'),
('INVENTORY_CLERK', 'Inventory Clerk', 'Stock management'),
('AUDITOR', 'Auditor', 'Compliance and audit access');
```

**Seed Data - Default Admin User**
```sql
-- Password: admin123 (hashed with Werkzeug)
INSERT INTO user (email, password_hash, first_name, last_name, is_active)
VALUES ('admin@gov.jm', 'scrypt:32768:8:1$...', 'System', 'Administrator', TRUE);

-- Assign admin role
INSERT INTO user_role (user_id, role_id)
SELECT u.id, r.id FROM user u, role r
WHERE u.email = 'admin@gov.jm' AND r.code = 'SYSTEM_ADMINISTRATOR';
```

**Seed Data - Sample Warehouses**
```sql
INSERT INTO warehouse (warehouse_name, warehouse_type, address1_text, parish_code, contact_name, 
    phone_no, custodian_id, status_code, create_by_id, create_dtime, update_by_id, update_dtime, version_nbr)
SELECT 'NATIONAL WAREHOUSE - KINGSTON', 'MAIN', 'Spanish Town Road', '01', 'WAREHOUSE MANAGER',
    '876-123-4567', c.custodian_id, 'A', 'SYSTEM', CURRENT_TIMESTAMP, 'SYSTEM', CURRENT_TIMESTAMP, 1
FROM custodian c WHERE c.custodian_name LIKE '%ODPEM%';

INSERT INTO warehouse (warehouse_name, warehouse_type, address1_text, parish_code, contact_name, 
    phone_no, custodian_id, status_code, create_by_id, create_dtime, update_by_id, update_dtime, version_nbr)
SELECT 'SUB-HUB MONTEGO BAY', 'SUB-HUB', 'Howard Cooke Highway', '08', 'SUB-HUB SUPERVISOR',
    '876-234-5678', c.custodian_id, 'A', 'SYSTEM', CURRENT_TIMESTAMP, 'SYSTEM', CURRENT_TIMESTAMP, 1
FROM custodian c WHERE c.custodian_name LIKE '%ODPEM%';
```

**Seed Data - Sample Agencies**
```sql
INSERT INTO agency (agency_name, address1_text, parish_code, contact_name, phone_no,
    create_by_id, create_dtime, update_by_id, update_dtime, version_nbr) VALUES
('ST. ANN COMMUNITY CENTER', 'Main Street, Ocho Rios', '06', 'CENTER COORDINATOR', 
 '876-345-6789', 'SYSTEM', CURRENT_TIMESTAMP, 'SYSTEM', CURRENT_TIMESTAMP, 1),
('WESTMORELAND SHELTER', 'Savanna-la-Mar Town Center', '10', 'SHELTER MANAGER',
 '876-456-7890', 'SYSTEM', CURRENT_TIMESTAMP, 'SYSTEM', CURRENT_TIMESTAMP, 1);
```

---

## 3. ROLE-BASED ACCESS CONTROL

### 3.1 Role Definitions

| Role Code | Display Name | Access Level | Key Permissions |
|-----------|--------------|--------------|-----------------|
| SYSTEM_ADMINISTRATOR | System Administrator | Full Access | User management, system configuration, all operations |
| LOGISTICS_MANAGER | Logistics Manager | Strategic | Approve needs lists, view all hubs, analytics, reporting |
| LOGISTICS_OFFICER | Logistics Officer | Operational | Prepare fulfilments, manage dispatches, stock allocation |
| MAIN_HUB_WAREHOUSE | Main Hub Warehouse | Hub-Specific | Stock management at main hub, intake operations |
| SUB_HUB_WAREHOUSE | Sub Hub Warehouse | Hub-Specific | Stock management at sub-hub, local distributions |
| AGENCY_HUB | Agency Hub | Request-Only | Submit needs lists, receive deliveries, track requests |
| INVENTORY_CLERK | Inventory Clerk | Data Entry | Item creation, stock updates, basic reporting |
| AUDITOR | Auditor | Read-Only | Full transaction history, compliance reports, no modifications |

### 3.2 Permission Matrix

| Operation | ADMIN | LOG_MGR | LOG_OFF | MAIN_HUB | SUB_HUB | AGENCY | INV_CLK | AUDITOR |
|-----------|-------|---------|---------|----------|---------|--------|---------|---------|
| Create Users | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Manage Locations | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Create Items | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ | ✗ |
| Intake Stock | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ | ✗ |
| Submit Needs List | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ |
| Review Needs List | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Approve Needs List | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Prepare Fulfilment | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Dispatch Fulfilment | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ |
| Receive Fulfilment | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ |
| View All Transactions | ✓ | ✓ | ✓ | Hub | Hub | Hub | Hub | ✓ |
| Generate Reports | ✓ | ✓ | ✓ | Hub | Hub | Hub | Hub | ✓ |

---

## 4. FUNCTIONAL REQUIREMENTS

### 4.1 Authentication & User Management

**FR-AUTH-001**: Login System
- Users authenticate with email and password
- Password hashing using Werkzeug (scrypt algorithm)
- Session management via Flask-Login
- "Remember Me" functionality
- Automatic session timeout after 30 minutes of inactivity
- Redirect to intended page after login

**FR-AUTH-002**: User Creation (Admin Only)
- Create new user accounts
- Assign roles (single or multiple)
- Assign hub access (location scoping)
- Set user status (Active/Inactive)
- Capture user profile (name, email, phone, job title, organization)

**FR-AUTH-003**: Password Management
- Secure password hashing on registration
- Password change functionality
- Password reset (future enhancement)

### 4.2 Dashboard & Analytics

**FR-DASH-001**: Role-Based Dashboards
Each role sees a customized dashboard:

**System Administrator Dashboard:**
- System health metrics
- User activity overview
- All hub statistics
- System-wide alerts
- Recent transactions (all locations)
- User management quick actions

**Logistics Manager Dashboard:**
- Pending needs lists (all agencies)
- Fulfillment pipeline status
- Hub capacity overview
- Low stock alerts (all hubs)
- Distribution metrics
- Approval queue

**Logistics Officer Dashboard:**
- Active fulfilments in preparation
- Dispatch ready items
- Stock allocation status
- Transfer requests
- Quick stock lookup

**Main Hub/Sub Hub Warehouse Dashboard:**
- Current hub inventory levels
- Intake/distribution activity (hub-specific)
- Low stock alerts (hub-specific)
- Pending transfers
- Recent transactions (hub-specific)
- Quick intake/distribute actions

**Agency Hub Dashboard:**
- My needs lists (draft, submitted, approved, completed)
- Pending deliveries
- Recent receipts
- Submit new needs list action
- Notifications center

**Inventory Clerk Dashboard:**
- Item management
- Stock entry quick actions
- Recent entries
- Data quality alerts

**Auditor Dashboard:**
- Transaction audit log
- Compliance metrics
- Report generation
- Full system read access

**FR-DASH-002**: Key Performance Indicators
All dashboards include relevant KPIs:
- Total active items
- Total stock quantity
- Active disaster events
- Total donors
- Total beneficiaries
- Active locations
- Transaction counts (30-day and all-time)

**FR-DASH-003**: Visual Alerts
- Color-coded low stock alerts (Red: <25%, Yellow: 25-50%, Green: >50%)
- Expiring items (Critical: <7 days, Warning: 8-14 days, Attention: 15-30 days)
- Pending approvals counter
- Unread notifications badge

### 4.3 Item Management

**FR-ITEM-001**: Create Items
- Auto-generated SKU (format: ITM-XXXXXX)
- Manual or barcode entry
- Required fields: Name, Category, Unit of Measure
- Optional fields: Description, Storage Requirements, Minimum Quantity
- Attachment upload (images, documents, up to 10MB)
- Categories: Food, Water, Hygiene, Medical, Shelter, Clothing, Construction, Tools, Other

**FR-ITEM-002**: Edit Items
- Update all item fields
- Cannot change SKU after creation
- Audit trail of changes

**FR-ITEM-003**: Item Search & Filter
- Search by name, SKU, barcode, category
- Filter by category
- Sort by name, SKU, stock level
- Pagination (50 items per page)

**FR-ITEM-004**: Item Import/Export
- CSV import for bulk item creation
- CSV export for reporting
- Template download for imports

**FR-ITEM-005**: Item Details View
- Complete item information
- Current stock by location
- Transaction history
- Expiry tracking
- Attachment preview/download

### 4.4 Location Management

**FR-LOC-001**: Create Locations (Depots/Hubs)
- Three hub types:
  - MAIN: Central warehouses
  - SUB: Regional distribution centers
  - AGENCY: Request-only locations (shelters, community centers)
- Hierarchical structure (SUB and AGENCY can have parent MAIN hub)
- Status: Active/Inactive
- Operational timestamp tracking

**FR-LOC-002**: Location Inventory View
- Stock levels by item
- Filter by category
- Search by item name/SKU
- Show expiry dates
- Low stock highlighting

**FR-LOC-003**: Hub Transfer
- Transfer requests between hubs
- Approval workflow for transfers
- Automatic stock adjustment on approval

### 4.5 Disaster Event Management

**FR-EVENT-001**: Create Disaster Events
- Required fields: Name, Type, Start Date, Description, Status
- Event types: Hurricane, Earthquake, Flood, Tsunami, Fire, Tornado, Epidemic, War
- Status: Active/Closed
- End date (when closed)

**FR-EVENT-002**: Event Tracking
- All intake operations must link to an active event
- All needs lists must link to an event
- Event-based reporting
- Activity timeline by event

**FR-EVENT-003**: Event Closure
- Close event (requires end date)
- View historical events
- Generate event summary reports

### 4.6 Intake Operations

**FR-INTAKE-001**: Record Incoming Supplies
- Required fields:
  - Item (dropdown with search)
  - Quantity
  - Destination location
  - Disaster event
  - Donor
- Optional fields:
  - Expiry date
  - Notes
- Auto-creates donor if new
- Validates stock availability at location
- Records user who performed intake
- Timestamp of operation

**FR-INTAKE-002**: Batch Intake
- Add multiple items in single operation
- All items link to same donor and event
- Separate quantities and expiry dates per item

**FR-INTAKE-003**: Intake Validation
- Quantity must be positive integer
- Location must be active
- Event must be active
- Item must exist

### 4.7 Needs List Workflow

**FR-NEEDS-001**: Create Needs List (Agency Hub)
- Auto-generated list number (format: NL-XXXXXX)
- Required fields:
  - Requesting agency (auto-filled from user's hub)
  - Disaster event
  - Submission type: DRAFT, NEEDS (informal), FORMAL_REQUEST
  - Priority: LOW, MEDIUM, HIGH, CRITICAL
  - Urgency: ROUTINE, URGENT, EMERGENCY
  - Requester name and contact
- Add line items:
  - Item (dropdown)
  - Requested quantity
  - Justification (required for HIGH/CRITICAL priority)
  - Notes (optional)
- Save as draft or submit immediately
- Edit while in draft status
- Delete draft lists

**FR-NEEDS-002**: Submit Needs List
- Validation:
  - At least one line item
  - All quantities positive
  - Justification provided for high priority items
- Status changes: Draft → Submitted
- Timestamp recorded
- Notification sent to Logistics Manager
- List becomes locked after submission (no further edits without approval)

**FR-NEEDS-003**: Review Needs List (Logistics Manager)
- View all submitted needs lists
- Filter by: Status, Priority, Urgency, Agency, Date range
- Review each line item
- For each item, set:
  - Approved quantity (can be less than requested)
  - Status: Approved, Partially Approved, Rejected
  - Review notes
- Overall list actions:
  - Approve (status: Under Review → Approved)
  - Request changes (status: Under Review → Submitted with notes)
  - Reject (status: Under Review → Rejected)
- Notification sent to agency on decision

**FR-NEEDS-004**: Needs List Status Workflow
```
Draft → Submitted → Under Review → Approved → In Preparation → 
Dispatched → Received → Completed
```
Alternative paths:
- Rejected (from Under Review)
- Cancelled (from any status by Logistics Manager)

**FR-NEEDS-005**: Lock/Unlock Mechanism
- Lists auto-lock on submission
- Logistics Manager can unlock for agency to edit
- Re-submission required after unlock edits
- Lock status displayed prominently
- Lock banner shows who locked and when

### 4.8 Fulfilment Preparation

**FR-FUL-001**: Create Fulfilment (Logistics Officer)
- Link to approved needs list
- Auto-generated fulfilment number (format: FUL-XXXXXX)
- For each approved line item:
  - View requested and approved quantities
  - Select source location(s)
  - Allocate quantity from each source
  - View current stock at each location
  - Validate sufficient stock
- Mark as partial fulfillment if stock insufficient
- Add preparation notes

**FR-FUL-002**: Multi-Source Allocation
- Single line item can be fulfilled from multiple hubs
- Example: 100 units requested → 60 from Main Hub + 40 from Sub Hub
- Automatic stock validation for each source
- Visual stock level indicators

**FR-FUL-003**: Fulfilment Editing
- Edit allocated quantities before dispatch
- Change source locations
- Add/remove line items (if needs list allows)
- Edit log captures:
  - Field changed
  - Old value
  - New value
  - Reason for change
  - User who made change
  - Timestamp

**FR-FUL-004**: Stock Availability Check
- Real-time stock lookup by location
- Show available quantity
- Warning if allocation exceeds available stock
- Block dispatch if allocation invalid

**FR-FUL-005**: Fulfilment Status Workflow
```
In Preparation → Ready for Dispatch → Dispatched → Received → Completed
```
Alternative: Cancelled

### 4.9 Dispatch Operations

**FR-DISP-001**: Dispatch Fulfilment (Warehouse Staff)
- View fulfilments ready for dispatch
- For each fulfilment:
  - Generate dispatch manifest
  - Auto-generated manifest number (format: DSP-XXXXXX)
  - Required fields:
    - Vehicle information
    - Driver name
    - Driver contact
    - Dispatch notes
- For each line item:
  - Confirm dispatched quantity
  - Can adjust if partial dispatch
  - Add item-specific notes
- Record dispatcher identity and timestamp
- Stock deduction occurs on dispatch confirmation
- Notification sent to receiving agency

**FR-DISP-002**: Dispatch Manifest
- Printable dispatch document
- Contains:
  - Manifest number
  - Fulfilment number
  - Needs list number
  - From/To locations
  - Complete item list with quantities
  - Vehicle and driver details
  - Dispatch timestamp
  - Dispatcher signature line
  - Receiver signature line

**FR-DISP-003**: Partial Dispatch
- Allow dispatch of partial quantities
- Remaining quantities stay "Ready for Dispatch"
- Separate dispatch manifests for partial dispatches
- Clear indication of partial status

### 4.10 Receipt Operations

**FR-RCPT-001**: Receive Fulfilment (Agency Hub)
- View dispatched fulfilments (to my agency)
- For each fulfilment:
  - View manifest details
  - Confirm received quantities per item
  - Can report shortages
  - Can report damaged items
  - Document condition (Good, Damaged, Short)
  - Add discrepancy notes
  - Upload signature/photo (optional)
- Record receiver identity and timestamp
- Generate receipt record (auto-number: RCP-XXXXXX)

**FR-RCPT-002**: Receipt Validation
- Compare received vs dispatched quantities
- Flag discrepancies automatically
- Require explanation for shortages >10%
- Require explanation for damaged items
- Notification sent to dispatcher if discrepancies

**FR-RCPT-003**: Receipt Completion
- Status change: Dispatched → Received
- If all items received in full: Received → Completed
- If partial receipt: Status remains "Received" until subsequent dispatches

**FR-RCPT-004**: Stock Adjustment
- Receiving agency stock automatically updated
- If agency has no warehouse (pure AGENCY hub), receipt for tracking only
- If agency has warehouse capability, stock added to agency inventory

### 4.11 Distribution Operations (Legacy)

**FR-DIST-001**: Create Distribution Package
- Required fields:
  - Items (multiple)
  - Quantities
  - Recipient agency
  - Distributor/Beneficiary
  - Event
  - Location
- Validates stock availability
- Records distributor identity

**FR-DIST-002**: Distribution Validation
- Cannot distribute more than available stock
- Location stock reduced immediately
- Transaction record created (type: OUT)
- Distributor accountability tracking

### 4.12 Transfer Operations

**FR-TRANS-001**: Request Transfer
- Request transfer of items between hubs
- Required fields:
  - From location
  - To location
  - Item
  - Quantity
  - Justification
- Status: PENDING

**FR-TRANS-002**: Approve Transfer (Logistics Manager)
- View pending transfer requests
- Approve or reject with notes
- On approval:
  - Create two transactions:
    - OUT from source location
    - IN to destination location
  - Update stock levels
  - Status: APPROVED → COMPLETED

### 4.13 Reporting & Analytics

**FR-REPORT-001**: Stock Reports
- Stock by location
- Stock by category
- Low stock report
- Expiring items report (7-day, 14-day, 30-day windows)
- Zero stock items
- Overstocked items

**FR-REPORT-002**: Transaction Reports
- Transaction history (filterable by date, location, type, item)
- Intake summary by donor
- Distribution summary by beneficiary
- Event-based transaction summary
- Audit trail report

**FR-REPORT-003**: Needs List Reports
- Active needs lists by status
- Pending approvals
- Fulfillment pipeline status
- Agency request history
- Average fulfillment time

**FR-REPORT-004**: Export Functionality
- All reports exportable to CSV
- Date range selection
- Filter by location, category, event, status

### 4.14 Notification System

**FR-NOTIF-001**: In-App Notifications
- Notification types:
  - Needs list submitted
  - Needs list approved/rejected
  - Fulfilment prepared
  - Dispatch completed
  - Receipt confirmed
  - Comments added
  - Stock alerts
- Notification display:
  - Badge counter in header
  - Dropdown list with recent notifications
  - Click to navigate to related resource
- Notification actions:
  - Mark as read
  - Mark all as read
  - Archive
  - Delete

**FR-NOTIF-002**: Email Notifications (Future)
- Configurable email alerts
- User preference settings
- Email templates for each notification type

### 4.15 Offline Mode (Experimental)

**FR-OFFLINE-001**: Service Worker
- Cache critical assets
- Cache item list
- Cache location list
- Offline indicator in UI

**FR-OFFLINE-002**: Local Storage
- Queue transactions when offline
- Sync when connection restored
- Conflict resolution on sync

**FR-OFFLINE-003**: Encryption (Pending)
- Encrypt cached data
- Secure offline sessions
- Auto-expire offline sessions

---

## 5. NON-FUNCTIONAL REQUIREMENTS

### 5.1 Performance

**NFR-PERF-001**: Page Load Time
- Dashboard loads in <3 seconds
- List pages load in <2 seconds
- Search results display in <1 second

**NFR-PERF-002**: Database Query Performance
- All queries optimized with indexes
- Pagination for large result sets
- Eager loading to prevent N+1 queries

**NFR-PERF-003**: Scalability
- Support 100+ concurrent users
- Handle 10,000+ items in inventory
- Manage 50+ locations

### 5.2 Security

**NFR-SEC-001**: Authentication Security
- Secure password hashing (scrypt algorithm)
- Session-based authentication
- Session timeout after 30 minutes inactivity
- Protection against session hijacking

**NFR-SEC-002**: Authorization Security
- Role-based access control on all routes
- Decorator-based permission checking
- No direct URL access to unauthorized resources
- 403 Forbidden page for unauthorized access

**NFR-SEC-003**: Data Security
- SQL injection prevention (SQLAlchemy ORM)
- CSRF protection (Flask built-in)
- XSS protection (Jinja2 auto-escaping)
- Secure file upload validation

**NFR-SEC-004**: Audit Trail
- All transactions recorded with user attribution
- All needs list actions logged
- All fulfilment changes logged
- Immutable audit records

### 5.3 Usability

**NFR-USE-001**: Responsive Design
- Mobile-friendly interface
- Bootstrap 5 responsive grid
- Touch-friendly controls
- Readable on tablets and phones

**NFR-USE-002**: Accessibility
- ARIA labels for screen readers
- Keyboard navigation support
- Sufficient color contrast
- Clear error messages

**NFR-USE-003**: User Experience
- Intuitive navigation
- Clear visual hierarchy
- Consistent UI patterns
- Helpful tooltips and hints
- Confirmation dialogs for destructive actions

### 5.4 Reliability

**NFR-REL-001**: Uptime
- 99.9% availability target
- Graceful error handling
- User-friendly error messages

**NFR-REL-002**: Data Integrity
- Database transactions for multi-step operations
- Referential integrity constraints
- Validation at model and form level

**NFR-REL-003**: Backup & Recovery
- Daily database backups
- Point-in-time recovery capability
- Backup retention: 30 days

### 5.5 Maintainability

**NFR-MAINT-001**: Code Quality
- PEP 8 compliance
- Clear function and variable naming
- Comprehensive comments
- Modular architecture

**NFR-MAINT-002**: Documentation
- Inline code documentation
- README with setup instructions
- Database schema documentation
- API documentation (if applicable)

---

## 6. USER INTERFACE REQUIREMENTS

### 6.1 Design System

**UI-DESIGN-001**: Official GOJ Branding
- **Colors:**
  - Primary: GOJ Green (#006B3E)
  - Secondary: GOJ Gold (#FFD100)
  - Accent: Dark Green (#004D2C)
  - Background: White (#FFFFFF)
  - Text: Dark Gray (#333333)
  - Success: Green (#28A745)
  - Warning: Amber (#FFC107)
  - Danger: Red (#DC3545)
  - Info: Blue (#17A2B8)

**UI-DESIGN-002**: Typography
- Font Family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif
- Headers: Bold, GOJ Green
- Body: Regular weight
- Sizes: 1rem base, scale: 0.875rem, 1rem, 1.25rem, 1.5rem, 2rem

**UI-DESIGN-003**: Logo & Imagery
- Jamaica Coat of Arms in header
- ODPEM logo option
- Official government seal
- Professional disaster relief imagery

**UI-DESIGN-004**: Icons
- Bootstrap Icons 1.11.3
- Consistent icon usage across app
- Icons for all major actions
- Status indicators with icons

### 6.2 Layout Structure

**UI-LAYOUT-001**: Base Template
- Top navigation bar with:
  - Logo/Home link
  - Main navigation menu
  - User profile dropdown
  - Notifications bell icon
  - Logout button
- Sidebar (collapsible on mobile):
  - Role-specific menu items
  - Dashboard link
  - Quick actions
- Main content area:
  - Page title
  - Breadcrumb navigation
  - Content body
  - Action buttons (top-right)
- Footer:
  - Copyright notice
  - Version number
  - Support contact

**UI-LAYOUT-002**: Navigation Menu (Role-Based)
Each role sees relevant menu items:
- Dashboard
- Inventory (Items, Locations, Stock Reports)
- Operations (Intake, Distribution, Transfers)
- Needs Lists (My Lists, All Lists, Approvals)
- Fulfilments (Prepare, Dispatch, Receive)
- Reporting (Transactions, Analytics, Exports)
- Administration (Users, Roles, System Settings) - Admin only

**UI-LAYOUT-003**: Responsive Breakpoints
- Mobile: <576px
- Tablet: 576px - 768px
- Desktop: >768px
- Large Desktop: >1200px

### 6.3 Component Library

**UI-COMP-001**: Forms
- Consistent form styling
- Labels above inputs
- Required field indicators (*)
- Inline validation messages
- Help text below fields
- Primary action button (right-aligned)
- Secondary actions (left-aligned)
- Cancel/Back link

**UI-COMP-002**: Tables
- Striped rows for readability
- Hover effect on rows
- Sort indicators in headers
- Action buttons/icons in last column
- Pagination controls
- Search/filter at top
- Export button (top-right)

**UI-COMP-003**: Cards
- Used for dashboard KPIs
- Shadow for depth
- Icon in header
- Metric/count prominently displayed
- Subtitle or change indicator
- Optional action link

**UI-COMP-004**: Badges
- Status indicators
- Color-coded by status
- Rounded corners
- Small text

**UI-COMP-005**: Alerts
- Dismissible flash messages
- Color-coded by type (success, warning, danger, info)
- Auto-dismiss after 5 seconds (optional)
- Close button

**UI-COMP-006**: Modals
- Confirm destructive actions
- Quick forms (add donor, beneficiary)
- Detail views
- Lightbox for images

### 6.4 Page Templates

**UI-PAGE-001**: Login Page
- Centered form
- Jamaica coat of arms
- App title: "Disaster Relief Inventory Management System (DRIMS)"
- Subtitle: "Government of Jamaica"
- Email and password fields
- "Remember Me" checkbox
- Login button
- Minimal footer

**UI-PAGE-002**: Dashboard Page
- Role-specific layout
- KPI cards at top (4-column grid)
- Charts/graphs (if applicable)
- Recent activity section
- Quick actions section
- Alerts/notifications section

**UI-PAGE-003**: List Pages (Items, Locations, Events, etc.)
- Page title with item count
- Search bar and filters (top)
- Add New button (top-right)
- Data table
- Pagination controls (bottom)
- Export button

**UI-PAGE-004**: Form Pages (Create/Edit)
- Page title (Create X / Edit X)
- Breadcrumb navigation
- Form with sections (if complex)
- Required field indicators
- Validation messages inline
- Save and Cancel buttons
- Delete button (if editing)

**UI-PAGE-005**: Detail Pages
- Page title with identifier (e.g., "Item: ITM-000123")
- Breadcrumb navigation
- Information display (key-value pairs)
- Related data tables (e.g., stock by location)
- Action buttons (Edit, Delete, etc.)
- Activity/transaction history

**UI-PAGE-006**: Needs List Pages
- **Agency View:**
  - My Needs Lists table
  - Filter by status
  - Create New button
  - Edit draft lists
  - View submitted/approved lists
- **Logistics Manager View:**
  - All Needs Lists table
  - Filter by status, priority, urgency, agency
  - Review action for submitted lists
  - Unlock action for approved lists
- **Detail View:**
  - Header with list number, agency, status
  - Lock status banner (if locked)
  - Line items table with quantities and statuses
  - Notes and justification
  - Approval/rejection form (if manager)
  - Status history timeline

**UI-PAGE-007**: Fulfilment Pages
- **Prepare Fulfilment:**
  - Needs list details at top
  - Line items with approved quantities
  - For each item:
    - Source location dropdown(s)
    - Quantity allocation input(s)
    - Current stock indicator
    - Add source button (for multi-source)
  - Total allocated vs approved
  - Partial fulfillment checkbox
  - Notes field
  - Save Draft / Ready for Dispatch buttons
- **Dispatch View:**
  - Fulfilments ready for dispatch table
  - Dispatch action opens modal/form
  - Vehicle and driver fields
  - Confirm quantities
  - Generate manifest button
- **Receipt View:**
  - Dispatched fulfilments (to my agency)
  - Receipt action opens form
  - Confirm received quantities per item
  - Condition dropdown (Good, Damaged, Short)
  - Discrepancy notes
  - Signature upload
  - Confirm Receipt button

**UI-PAGE-008**: Reports Page
- Report type selector (dropdown or tabs)
- Date range picker
- Filter options (location, category, etc.)
- Generate button
- Results table
- Export to CSV button
- Print option

**UI-PAGE-009**: User Management Page (Admin)
- Users table
- Columns: Email, Name, Roles, Status, Last Login
- Add User button
- Edit user action (opens form/modal)
- Deactivate/Activate toggle
- Assign roles action
- Assign hubs action

---

## 7. VISUAL DESIGN SPECIFICATIONS

### 7.1 Status Color Coding

| Status | Color | Badge Class | Use Case |
|--------|-------|-------------|----------|
| Draft | Gray | badge-secondary | Needs lists, fulfilments in draft |
| Submitted | Blue | badge-info | Needs lists awaiting review |
| Under Review | Purple | badge-primary | Needs lists being reviewed |
| Approved | Green | badge-success | Approved needs lists |
| In Preparation | Orange | badge-warning | Fulfilments being prepared |
| Ready for Dispatch | Dark Orange | badge-warning | Fulfilments ready |
| Dispatched | Dark Blue | badge-primary | Dispatched fulfilments |
| Received | Light Green | badge-success | Received fulfilments |
| Completed | Dark Green | badge-success | Completed workflows |
| Rejected | Red | badge-danger | Rejected requests |
| Cancelled | Light Gray | badge-secondary | Cancelled operations |
| Partial | Yellow | badge-warning | Partial fulfilments |

### 7.2 Priority Color Coding

| Priority | Color | Icon | Badge Class |
|----------|-------|------|-------------|
| LOW | Light Gray | ⬇️ | badge-secondary |
| MEDIUM | Blue | ➡️ | badge-info |
| HIGH | Orange | ⬆️ | badge-warning |
| CRITICAL | Red | 🔺 | badge-danger |

### 7.3 Alert Severity

| Severity | Color | Icon | Use Case |
|----------|-------|------|----------|
| Low Stock (<50%) | Yellow | ⚠️ | Stock alert |
| Critical Stock (<25%) | Red | ❗ | Urgent stock alert |
| Expiring Soon (7-14 days) | Yellow | 📅 | Expiry warning |
| Expiring Critical (<7 days) | Red | 🚨 | Urgent expiry alert |

### 7.4 Icon Usage

| Action | Icon | Bootstrap Icon Class |
|--------|------|---------------------|
| Add/Create | ➕ | bi-plus-circle |
| Edit | ✏️ | bi-pencil |
| Delete | 🗑️ | bi-trash |
| View | 👁️ | bi-eye |
| Search | 🔍 | bi-search |
| Filter | 🔽 | bi-funnel |
| Export | 📥 | bi-download |
| Print | 🖨️ | bi-printer |
| Save | 💾 | bi-save |
| Submit | ➡️ | bi-send |
| Approve | ✅ | bi-check-circle |
| Reject | ❌ | bi-x-circle |
| Lock | 🔒 | bi-lock |
| Unlock | 🔓 | bi-unlock |
| Dispatch | 🚚 | bi-truck |
| Receive | 📦 | bi-box-arrow-in-down |
| Notification | 🔔 | bi-bell |
| User | 👤 | bi-person |
| Settings | ⚙️ | bi-gear |
| Dashboard | 📊 | bi-speedometer2 |
| Inventory | 📦 | bi-box-seam |
| Location | 📍 | bi-geo-alt |
| Event | 🌪️ | bi-exclamation-triangle |

---

## 8. TECHNICAL IMPLEMENTATION DETAILS

### 8.1 Flask Application Structure

```
drims/
├── app.py                          # Main Flask application
├── date_utils.py                   # Date/time formatting utilities
├── status_helpers.py               # Workflow status logic
├── storage_service.py              # File upload handling
├── seed_data.py                    # Database seeding script
├── requirements.txt                # Python dependencies
├── .env                            # Environment variables
├── .replit                         # Replit configuration
├── templates/                      # Jinja2 HTML templates
│   ├── base.html                  # Base template with navigation
│   ├── login.html                 # Login page
│   ├── dashboard.html             # Generic dashboard
│   ├── dashboard_*.html           # Role-specific dashboards
│   ├── items.html                 # Item list
│   ├── item_form.html             # Item create/edit
│   ├── depots.html                # Location list
│   ├── depot_form.html            # Location create/edit
│   ├── depot_inventory.html       # Location stock view
│   ├── events.html       # Event list
│   ├── event_form.html   # Event create/edit
│   ├── intake.html                # Intake form
│   ├── distribute.html            # Distribution form
│   ├── agency_needs_lists.html    # Agency needs list view
│   ├── all_needs_lists.html       # Admin/manager view
│   ├── needs_list_details.html    # Needs list detail
│   ├── logistics_*.html           # Logistics role views
│   ├── main_needs_lists.html      # Main hub view
│   └── 403.html                   # Forbidden page
├── static/                         # Static assets
│   ├── images/
│   │   ├── jamaica_coat_of_arms.png
│   │   └── odpem_logo.png
│   ├── js/
│   │   ├── offline.js             # Offline mode logic
│   │   ├── offline-storage.js     # Local storage management
│   │   └── offline-encryption.js  # Encryption utilities
│   ├── manifest.json              # PWA manifest
│   └── service-worker.js          # Service worker for offline
└── db.sqlite3                      # SQLite database (dev)
```

### 8.2 Flask Configuration

**Environment Variables (.env)**
```bash
SECRET_KEY=<generate-with-secrets.token_hex(32)>
DATABASE_URL=sqlite:///db.sqlite3  # or postgresql://...
OFFLINE_MODE_ENABLED=false
```

**Application Configuration (app.py)**
```python
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///db.sqlite3")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["OFFLINE_MODE_ENABLED"] = os.environ.get("OFFLINE_MODE_ENABLED", "false").lower() == "true"
```

### 8.3 Route Structure

| Route Pattern | Methods | Purpose | Roles |
|---------------|---------|---------|-------|
| `/` | GET | Redirect to dashboard | All authenticated |
| `/login` | GET, POST | User login | Anonymous |
| `/logout` | GET | User logout | All authenticated |
| `/dashboard` | GET | Role-based dashboard | All authenticated |
| `/items` | GET | Item list | All authenticated |
| `/items/new` | GET, POST | Create item | ADMIN, LOG_MGR, LOG_OFF, INV_CLK |
| `/items/<sku>` | GET | Item detail | All authenticated |
| `/items/<sku>/edit` | GET, POST | Edit item | ADMIN, LOG_MGR, LOG_OFF, INV_CLK |
| `/items/<sku>/delete` | POST | Delete item | ADMIN |
| `/items/import` | GET, POST | Import items CSV | ADMIN, LOG_MGR, INV_CLK |
| `/items/export` | GET | Export items CSV | All authenticated |
| `/locations` | GET | Location list | All authenticated |
| `/locations/new` | GET, POST | Create location | ADMIN, LOG_MGR |
| `/locations/<id>` | GET | Location detail | All authenticated |
| `/locations/<id>/edit` | GET, POST | Edit location | ADMIN, LOG_MGR |
| `/locations/<id>/inventory` | GET | Location stock | All authenticated |
| `/events` | GET | Event list | All authenticated |
| `/events/new` | GET, POST | Create event | ADMIN, LOG_MGR, LOG_OFF |
| `/events/<id>` | GET | Event detail | All authenticated |
| `/events/<id>/edit` | GET, POST | Edit event | ADMIN, LOG_MGR, LOG_OFF |
| `/intake` | GET, POST | Intake form | ADMIN, LOG_MGR, LOG_OFF, HUB_WAREHOUSE, INV_CLK |
| `/distribute` | GET, POST | Distribution form | ADMIN, LOG_MGR, LOG_OFF, HUB_WAREHOUSE |
| `/needs-lists` | GET | Needs list list | Role-specific view |
| `/needs-lists/new` | GET, POST | Create needs list | AGENCY_HUB |
| `/needs-lists/<id>` | GET | Needs list detail | Requester, LOG_MGR, LOG_OFF |
| `/needs-lists/<id>/edit` | GET, POST | Edit needs list | AGENCY_HUB (if draft/unlocked) |
| `/needs-lists/<id>/submit` | POST | Submit needs list | AGENCY_HUB |
| `/needs-lists/<id>/review` | GET, POST | Review needs list | LOG_MGR |
| `/needs-lists/<id>/approve` | POST | Approve needs list | LOG_MGR |
| `/needs-lists/<id>/reject` | POST | Reject needs list | LOG_MGR |
| `/needs-lists/<id>/unlock` | POST | Unlock needs list | LOG_MGR |
| `/needs-lists/<id>/cancel` | POST | Cancel needs list | LOG_MGR |
| `/fulfilments/prepare/<needs_list_id>` | GET, POST | Prepare fulfilment | LOG_MGR, LOG_OFF |
| `/fulfilments/<id>` | GET | Fulfilment detail | LOG_MGR, LOG_OFF, HUB_WAREHOUSE |
| `/fulfilments/<id>/edit` | GET, POST | Edit fulfilment | LOG_MGR, LOG_OFF |
| `/fulfilments/<id>/ready` | POST | Mark ready for dispatch | LOG_MGR, LOG_OFF |
| `/fulfilments/<id>/dispatch` | GET, POST | Dispatch fulfilment | LOG_MGR, LOG_OFF, HUB_WAREHOUSE |
| `/fulfilments/<id>/receive` | GET, POST | Receive fulfilment | AGENCY_HUB |
| `/transfers/request` | GET, POST | Request transfer | HUB_WAREHOUSE |
| `/transfers` | GET | Transfer list | ADMIN, LOG_MGR |
| `/transfers/<id>/approve` | POST | Approve transfer | LOG_MGR |
| `/transfers/<id>/reject` | POST | Reject transfer | LOG_MGR |
| `/reports/stock` | GET | Stock report | All authenticated |
| `/reports/transactions` | GET | Transaction report | All authenticated |
| `/reports/needs-lists` | GET | Needs list report | LOG_MGR, LOG_OFF, AUDITOR |
| `/reports/export` | GET | Export report CSV | All authenticated |
| `/admin/users` | GET | User list | ADMIN |
| `/admin/users/new` | GET, POST | Create user | ADMIN |
| `/admin/users/<id>/edit` | GET, POST | Edit user | ADMIN |
| `/admin/users/<id>/deactivate` | POST | Deactivate user | ADMIN |
| `/notifications` | GET | Notification list | All authenticated |
| `/notifications/<id>/read` | POST | Mark notification read | All authenticated |
| `/notifications/mark-all-read` | POST | Mark all read | All authenticated |
| `/api/items/search` | GET | Item search API | All authenticated |
| `/api/stock/<location_id>/<item_sku>` | GET | Stock availability API | All authenticated |

### 8.4 Authentication Decorators

**login_required Decorator** (Flask-Login)
```python
@app.route('/dashboard')
@login_required
def dashboard():
    # Route handler
```

**Role-Based Permission Decorator**
```python
def role_required(*allowed_roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('login'))
            if not current_user.has_any_role(*allowed_roles):
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Usage
@app.route('/admin/users')
@login_required
@role_required('SYSTEM_ADMINISTRATOR')
def admin_users():
    # Route handler
```

### 8.5 Template Context

**Global Template Variables**
```python
@app.context_processor
def inject_globals():
    return {
        'format_date': format_date,
        'format_datetime': format_datetime,
        'format_datetime_full': format_datetime_full,
        'format_time': format_time,
        'format_relative_time': format_relative_time,
        'get_needs_list_status_display': get_needs_list_status_display,
        'get_line_item_status': get_line_item_status,
        'current_year': datetime.utcnow().year,
        'app_version': '2.0.0',
        'offline_mode_enabled': app.config['OFFLINE_MODE_ENABLED']
    }
```

### 8.6 Date/Time Formatting

**date_utils.py Functions**
```python
def format_date(dt):
    """Format date as MMM DD, YYYY (Jan 15, 2025)"""
    
def format_datetime(dt):
    """Format datetime as MMM DD, YYYY HH:MM AM/PM (Jan 15, 2025 02:30 PM)"""
    
def format_datetime_full(dt):
    """Format datetime as Day, MMM DD, YYYY HH:MM AM/PM (Monday, Jan 15, 2025 02:30 PM)"""
    
def format_time(dt):
    """Format time as HH:MM AM/PM (02:30 PM)"""
    
def format_datetime_iso_est(dt):
    """Format datetime as ISO with EST timezone (2025-01-15T14:30:00-05:00)"""
    
def format_relative_time(dt):
    """Format relative time (2 hours ago, 3 days ago, etc.)"""
```

### 8.7 Status Helper Functions

**status_helpers.py Functions**
```python
def get_line_item_status(needs_list, line_item):
    """Determine line item status based on workflow state"""
    # Returns: Pending, Approved, Partially Approved, Rejected, 
    #          In Preparation, Dispatched, Received, etc.
    
def get_needs_list_status_display(needs_list):
    """Get user-friendly status display with badge class"""
    # Returns: {'status': 'Under Review', 'badge_class': 'badge-info'}
```

### 8.8 File Upload Handling

**storage_service.py Functions**
```python
def get_storage():
    """Get storage backend (local filesystem)"""
    
def allowed_file(filename):
    """Check if file extension is allowed"""
    # Allowed: .jpg, .jpeg, .png, .gif, .pdf, .doc, .docx, .xls, .xlsx
    
def validate_file_size(file, max_size_mb=10):
    """Validate file size (default max: 10MB)"""
    
def save_file(file, folder='uploads'):
    """Save uploaded file to storage"""
    # Returns: (filename, storage_path)
```

### 8.9 Database Seeding

**seed_data.py Script**
```python
def seed_roles():
    """Seed role table with standard roles"""
    
def seed_locations():
    """Seed sample locations (hubs)"""
    
def seed_items():
    """Seed sample relief items"""
    
def seed_events():
    """Seed sample disaster events"""
    
def seed_users():
    """Seed default users (admin, test users)"""
    
def seed_all():
    """Run all seed functions"""
```

Run seeding:
```bash
python seed_data.py
```

---

## 9. DEPLOYMENT REQUIREMENTS

### 9.1 Replit Configuration

**.replit File**
```ini
entrypoint = "app.py"
modules = ["python-3.11", "postgresql-16"]

[nix]
channel = "stable-25_05"
packages = ["glibcLocales", "sqlite"]

[deployment]
run = ["python3", "app.py"]
deploymentTarget = "cloudrun"

[workflows]
runButton = "Project"

[[workflows.workflow]]
name = "Project"
mode = "parallel"
author = "agent"

[[workflows.workflow.tasks]]
task = "workflow.run"
args = "Flask Server"

[[workflows.workflow]]
name = "Flask Server"
author = "agent"

[[workflows.workflow.tasks]]
task = "shell.exec"
args = "python app.py"
waitForPort = 5000

[workflows.workflow.metadata]
outputType = "webview"

[[ports]]
localPort = 5000
externalPort = 80
```

### 9.2 Python Dependencies

**requirements.txt**
```
Flask==3.0.3
Flask-SQLAlchemy==3.1.1
Flask-Login==0.6.3
SQLAlchemy==2.0.32
Werkzeug==3.0.3
pandas==2.2.2
python-dotenv==1.0.1
psycopg2-binary==2.9.9
gunicorn==21.2.0
```

### 9.3 Database Initialization

**Setup Script (setup_database.py)**
```python
from app import app, db
from seed_data import seed_all

with app.app_context():
    # Create all tables
    db.create_all()
    print("✓ Database tables created")
    
    # Seed data
    seed_all()
    print("✓ Database seeded")
    
    print("\nSetup complete! You can now log in with:")
    print("Email: admin@gov.jm")
    print("Password: admin123")
```

Run setup:
```bash
python setup_database.py
```

### 9.4 Environment Configuration

**Development (.env)**
```bash
SECRET_KEY=dev-secret-change-in-production
DATABASE_URL=sqlite:///db.sqlite3
OFFLINE_MODE_ENABLED=false
FLASK_ENV=development
FLASK_DEBUG=1
```

**Production (.env)**
```bash
SECRET_KEY=<generated-secret-key>
DATABASE_URL=postgresql://drims_user:secure_password@localhost/drims_db
OFFLINE_MODE_ENABLED=false
FLASK_ENV=production
FLASK_DEBUG=0
```

### 9.5 PostgreSQL Setup (Production)

**Database Creation**
```sql
CREATE DATABASE drims_db;
CREATE USER drims_user WITH PASSWORD 'secure_password';
GRANT ALL PRIVILEGES ON DATABASE drims_db TO drims_user;
```

**Connection String**
```
DATABASE_URL=postgresql://drims_user:secure_password@localhost/drims_db
```

---

## 10. TESTING REQUIREMENTS

### 10.1 Test Users

Create test users for each role:

```python
# System Administrator
Email: admin@gov.jm
Password: admin123
Role: SYSTEM_ADMINISTRATOR

# Logistics Manager
Email: logistics.manager@gov.jm
Password: logmanager123
Role: LOGISTICS_MANAGER

# Logistics Officer
Email: logistics.officer@gov.jm
Password: logofficer123
Role: LOGISTICS_OFFICER

# Main Hub Warehouse
Email: main.warehouse@gov.jm
Password: mainwarehouse123
Role: MAIN_HUB_WAREHOUSE
Hub: Main Hub (Kingston)

# Sub Hub Warehouse
Email: sub.warehouse@gov.jm
Password: subwarehouse123
Role: SUB_HUB_WAREHOUSE
Hub: Sub Hub (Montego Bay)

# Agency Hub
Email: agency@gov.jm
Password: agency123
Role: AGENCY_HUB
Hub: Agency Hub (St. Ann Community Center)

# Inventory Clerk
Email: clerk@gov.jm
Password: clerk123
Role: INVENTORY_CLERK

# Auditor
Email: auditor@gov.jm
Password: auditor123
Role: AUDITOR
```

### 10.2 Test Scenarios

**Scenario 1: Complete Needs List Workflow**
1. Login as Agency Hub user
2. Create new needs list
3. Add 5 items with various quantities
4. Save as draft
5. Edit draft
6. Submit needs list
7. Logout

8. Login as Logistics Manager
9. View submitted needs list
10. Review each line item
11. Approve some items in full
12. Partially approve some items
13. Reject some items
14. Add review notes
15. Approve needs list
16. Logout

17. Login as Logistics Officer
18. View approved needs list
19. Prepare fulfilment
20. Allocate stock from multiple sources
21. Mark ready for dispatch
22. Logout

23. Login as Main Hub Warehouse user
24. View fulfilment ready for dispatch
25. Enter vehicle and driver details
26. Dispatch fulfilment
27. Generate dispatch manifest
28. Logout

29. Login as Agency Hub user
30. View dispatched fulfilment
31. Confirm receipt of all items
32. Complete receipt
33. Verify needs list status is "Completed"

**Scenario 2: Stock Management**
1. Login as Inventory Clerk
2. Create 10 new items (various categories)
3. Logout

4. Login as Main Hub Warehouse user
5. Record intake of 5 items (link to active event)
6. Add donor information
7. Set expiry dates for perishable items
8. Verify stock levels increased
9. Logout

10. Login as Logistics Officer
11. View stock report by location
12. View low stock alert
13. Create transfer request (Main Hub → Sub Hub)
14. Logout

15. Login as Logistics Manager
16. View pending transfer request
17. Approve transfer
18. Verify stock updated at both locations

**Scenario 3: Reporting**
1. Login as Auditor
2. Generate transaction report (last 30 days)
3. Filter by location
4. Filter by disaster event
5. Export to CSV
6. Generate stock report by category
7. View low stock items
8. View expiring items (next 14 days)
9. Generate needs list report
10. View fulfilment pipeline status

**Scenario 4: User Management (Admin)**
1. Login as System Administrator
2. Create new user (Logistics Officer role)
3. Assign user to specific hub
4. Edit user details
5. Deactivate user
6. Reactivate user
7. Change user role
8. View user activity log

### 10.3 Performance Testing

- Load test with 50 concurrent users
- Test dashboard load time with 1000+ items
- Test needs list submission with 50+ line items
- Test stock report generation with 10,000+ transactions
- Test search performance with 5000+ items

### 10.4 Security Testing

- Attempt to access unauthorized routes
- Test SQL injection protection
- Test XSS protection
- Test CSRF token validation
- Test password hashing strength
- Test session hijacking prevention

---

## 11. MAINTENANCE & SUPPORT

### 11.1 Logging

**Application Logging**
- Log all authentication attempts
- Log all critical operations (approval, dispatch, receipt)
- Log all errors and exceptions
- Log performance metrics
- Store logs in: `/var/log/drims/app.log`

**Database Logging**
- Enable PostgreSQL query logging (slow queries >1s)
- Store logs in: `/var/log/postgresql/`

### 11.2 Monitoring

**Health Check Endpoint**
```python
@app.route('/health')
def health_check():
    return jsonify({
        'status': 'healthy',
        'database': 'connected',
        'version': '2.0.0',
        'timestamp': datetime.utcnow().isoformat()
    })
```

**Metrics to Monitor**
- Active users
- Database connection pool
- Response times
- Error rates
- Disk usage
- Database size

### 11.3 Backup Strategy

**Database Backups**
- Daily full backup at 2:00 AM
- Hourly incremental backups
- Retention: 30 days
- Backup location: `/backups/drims/`

**Backup Script (backup.sh)**
```bash
#!/bin/bash
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
pg_dump drims_db > /backups/drims/drims_db_$TIMESTAMP.sql
gzip /backups/drims/drims_db_$TIMESTAMP.sql
```

### 11.4 Update Procedures

**Application Updates**
1. Backup database
2. Pull latest code
3. Install dependencies: `pip install -r requirements.txt`
4. Run migrations (if any)
5. Restart application
6. Verify health check
7. Monitor logs

**Database Schema Changes**
- Use migration scripts
- Test on staging first
- Backup before applying
- Document all changes
- Rollback plan ready

---

## 12. FUTURE ENHANCEMENTS

### 12.1 Planned Features

**Phase 2:**
- Email notifications
- SMS alerts for critical events
- Mobile app (iOS/Android)
- Barcode scanning with mobile camera
- RFID tag support
- Advanced analytics dashboard
- Predictive stock alerts using ML

**Phase 3:**
- API for third-party integrations
- Webhook support
- Real-time collaboration (WebSocket)
- Advanced reporting (custom report builder)
- GIS mapping for distribution routes
- Drone delivery integration
- Blockchain for audit trail

### 12.2 Technical Debt

- Migrate to Flask-Migrate for database migrations
- Implement comprehensive unit tests (pytest)
- Add API documentation (OpenAPI/Swagger)
- Implement rate limiting
- Add two-factor authentication
- Improve offline mode security (encryption)
- Optimize database queries (add more indexes)
- Implement caching (Redis)

---

## APPENDIX A: SQL SCHEMA (Complete)

```sql
-- See section 2 for complete database schema
-- This appendix references the full SQL from aidmgmt-3.sql
-- and the simplified schema used in the application
```

The complete SQL schema is provided in Section 2 of this document. For the full original schema from the client, refer to the `aidmgmt-3.sql` file provided.

---

## APPENDIX B: GLOSSARY

| Term | Definition |
|------|------------|
| Agency Hub | A request-only location (shelter, community center) that submits needs lists and receives deliveries |
| Main Hub | Central warehouse with full inventory management capabilities |
| Sub Hub | Regional distribution center that can receive from Main Hub and distribute locally |
| Needs List | Formal request for relief items from an agency to logistics management |
| Fulfilment | The allocation and preparation of items to satisfy a needs list |
| Dispatch | The physical sending of items from one location to another |
| Receipt | The confirmation of items received at destination |
| Line Item | Individual item entry within a needs list or fulfilment |
| SKU | Stock Keeping Unit - unique identifier for an item |
| Donor | Entity that provides relief items |
| Beneficiary | Person or group receiving relief items |
| Transaction | Record of stock movement (intake or distribution) |
| Intake | Process of receiving items into inventory |
| Distribution | Process of giving items to beneficiaries (legacy workflow) |
| Transfer | Movement of items between locations |
| Event | Disaster event (hurricane, earthquake, etc.) |
| UOM | Unit of Measure (e.g., boxes, kg, liters, pieces) |

---

## APPENDIX C: CONTACT & SUPPORT

**Project Owner:**  
Government of Jamaica  
Office of Disaster Preparedness and Emergency Management (ODPEM)

**Technical Support:**  
System Administrator  
Email: admin@gov.jm

**For Issues:**  
Submit issue in project repository or contact system administrator

---

**Document Version:** 2.0  
**Last Updated:** November 11, 2025  
**Prepared For:** Replit Implementation  
**Status:** Final

---

**© 2025 Government of Jamaica. All rights reserved.**
