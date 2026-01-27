--
-- Add missing AIDMGMT-3 intake and return workflow tables
-- Tables: xfintake, xfintake_item, xfreturn, xfreturn_item, rtintake, rtintake_item
--

-- Transfer Intake: receiving transfers at destination warehouse
CREATE TABLE xfintake (
    transfer_id INTEGER NOT NULL REFERENCES transfer(transfer_id),
    inventory_id INTEGER NOT NULL REFERENCES inventory(inventory_id),
    intake_date DATE NOT NULL CHECK (intake_date <= CURRENT_DATE),
    comments_text VARCHAR(255),
    status_code CHAR(1) NOT NULL CHECK (status_code IN ('I','C','V')),
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE,
    verify_by_id VARCHAR(20) NOT NULL,
    verify_dtime TIMESTAMP(0) WITHOUT TIME ZONE,
    version_nbr INTEGER NOT NULL,
    CONSTRAINT pk_xfintake PRIMARY KEY(transfer_id, inventory_id)
);

-- Transfer Intake Items
CREATE TABLE xfintake_item (
    transfer_id INTEGER NOT NULL,
    inventory_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    usable_qty DECIMAL(12,2) NOT NULL CHECK (usable_qty >= 0.00),
    location1_id INTEGER REFERENCES location(location_id),
    defective_qty DECIMAL(12,2) NOT NULL CHECK (defective_qty >= 0.00),
    location2_id INTEGER REFERENCES location(location_id),
    expired_qty DECIMAL(12,2) NOT NULL CHECK (expired_qty >= 0.00),
    location3_id INTEGER REFERENCES location(location_id),
    uom_code VARCHAR(25) NOT NULL REFERENCES unitofmeasure(uom_code),
    status_code CHAR(1) NOT NULL CHECK (status_code IN ('P','V')),
    comments_text VARCHAR(255),
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    version_nbr INTEGER NOT NULL,
    CONSTRAINT fk_xfintake_item_intake FOREIGN KEY (transfer_id, inventory_id) 
        REFERENCES xfintake(transfer_id, inventory_id),
    CONSTRAINT pk_xfintake_item PRIMARY KEY(transfer_id, inventory_id, item_id)
);

CREATE INDEX dk_xfintake_item_1 ON xfintake_item(inventory_id, item_id);
CREATE INDEX dk_xfintake_item_2 ON xfintake_item(item_id);

-- Transfer Return: items being returned from destination to source warehouse
CREATE TABLE xfreturn (
    xfreturn_id SERIAL PRIMARY KEY,
    fr_inventory_id INTEGER NOT NULL REFERENCES inventory(inventory_id),
    to_inventory_id INTEGER NOT NULL REFERENCES inventory(inventory_id),
    return_date DATE NOT NULL DEFAULT CURRENT_DATE CHECK (return_date <= CURRENT_DATE),
    reason_text VARCHAR(255),
    status_code CHAR(1) NOT NULL CHECK (status_code IN ('D','C','V')),
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE,
    verify_by_id VARCHAR(20) NOT NULL,
    verify_dtime TIMESTAMP(0) WITHOUT TIME ZONE,
    version_nbr INTEGER NOT NULL
);

CREATE INDEX dk_xfreturn_1 ON xfreturn(return_date);
CREATE INDEX dk_xfreturn_2 ON xfreturn(fr_inventory_id);
CREATE INDEX dk_xfreturn_3 ON xfreturn(to_inventory_id);

-- Transfer Return Items
CREATE TABLE xfreturn_item (
    xfreturn_id INTEGER NOT NULL REFERENCES xfreturn(xfreturn_id),
    inventory_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    usable_qty DECIMAL(12,2) NOT NULL CHECK (usable_qty >= 0.00),
    defective_qty DECIMAL(12,2) NOT NULL CHECK (defective_qty >= 0.00),
    expired_qty DECIMAL(12,2) NOT NULL CHECK (expired_qty >= 0.00),
    uom_code VARCHAR(25) NOT NULL REFERENCES unitofmeasure(uom_code),
    reason_text VARCHAR(255),
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    version_nbr INTEGER NOT NULL,
    CONSTRAINT fk_xfreturn_item_inventory FOREIGN KEY(item_id, inventory_id) 
        REFERENCES inventory(item_id, inventory_id),
    CONSTRAINT pk_xfreturn_item PRIMARY KEY(xfreturn_id, inventory_id, item_id)
);

-- Return Intake: receiving returned items at source warehouse
CREATE TABLE rtintake (
    xfreturn_id INTEGER NOT NULL REFERENCES xfreturn(xfreturn_id),
    inventory_id INTEGER NOT NULL REFERENCES inventory(inventory_id),
    intake_date DATE NOT NULL CHECK (intake_date <= CURRENT_DATE),
    comments_text VARCHAR(255),
    status_code CHAR(1) NOT NULL CHECK (status_code IN ('I','C','V')),
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE,
    verify_by_id VARCHAR(20) NOT NULL,
    verify_dtime TIMESTAMP(0) WITHOUT TIME ZONE,
    version_nbr INTEGER NOT NULL,
    CONSTRAINT pk_rtintake PRIMARY KEY(xfreturn_id, inventory_id)
);

-- Return Intake Items
CREATE TABLE rtintake_item (
    xfreturn_id INTEGER NOT NULL,
    inventory_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    usable_qty DECIMAL(12,2) NOT NULL CHECK (usable_qty >= 0.00),
    location1_id INTEGER REFERENCES location(location_id),
    defective_qty DECIMAL(12,2) NOT NULL CHECK (defective_qty >= 0.00),
    location2_id INTEGER REFERENCES location(location_id),
    expired_qty DECIMAL(12,2) NOT NULL CHECK (expired_qty >= 0.00),
    location3_id INTEGER REFERENCES location(location_id),
    uom_code VARCHAR(25) NOT NULL REFERENCES unitofmeasure(uom_code),
    status_code CHAR(1) NOT NULL CHECK (status_code IN ('P','V')),
    comments_text VARCHAR(255),
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    version_nbr INTEGER NOT NULL,
    CONSTRAINT fk_rtintake_item_intake FOREIGN KEY (xfreturn_id, inventory_id) 
        REFERENCES rtintake(xfreturn_id, inventory_id),
    CONSTRAINT pk_rtintake_item PRIMARY KEY(xfreturn_id, inventory_id, item_id)
);

CREATE INDEX dk_rtintake_item_1 ON rtintake_item(inventory_id, item_id);
CREATE INDEX dk_rtintake_item_2 ON rtintake_item(item_id);
