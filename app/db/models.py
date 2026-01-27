"""
SQLAlchemy models for DRIMS
Maps to existing database schema (no auto-create)
"""
from app.db import db
from flask_login import UserMixin
from datetime import datetime
from sqlalchemy import CheckConstraint
from sqlalchemy.orm import backref
from app.utils.timezone import now as jamaica_now

class User(UserMixin, db.Model):
    """User authentication model with MFA and lockout support"""
    __tablename__ = 'user'
    user_uuid = db.Column(db.Uuid, nullable=False, unique=True)
    user_id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(200), unique=True, nullable=False)
    username = db.Column(db.String(60), unique=True)
    user_name = db.Column(db.String(20), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    password_algo = db.Column(db.String(20), nullable=False, default='argon2id')
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    full_name = db.Column(db.String(200))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    organization = db.Column(db.String(200))
    job_title = db.Column(db.String(200))
    phone = db.Column(db.String(50))
    timezone = db.Column(db.String(50), nullable=False, default='America/Jamaica')
    language = db.Column(db.String(10), nullable=False, default='en')
    notification_preferences = db.Column(db.Text)
    assigned_warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouse.warehouse_id'))
    last_login_at = db.Column(db.DateTime)
    create_dtime = db.Column(db.DateTime, nullable=False, default=jamaica_now)
    update_dtime = db.Column(db.DateTime, nullable=False, default=jamaica_now)
    
    mfa_enabled = db.Column(db.Boolean, nullable=False, default=False)
    mfa_secret = db.Column(db.String(64))
    failed_login_count = db.Column(db.SmallInteger, nullable=False, default=0)
    login_count = db.Column(db.Integer, nullable=False, default=0)
    lock_until_at = db.Column(db.DateTime)
    password_changed_at = db.Column(db.DateTime)
    
    agency_id = db.Column(db.Integer, db.ForeignKey('agency.agency_id'))
    status_code = db.Column(db.CHAR(1), nullable=False, default='A')
    version_nbr = db.Column(db.Integer, nullable=False, default=1)
    
    roles = db.relationship('Role', 
                           secondary='user_role', 
                           primaryjoin='User.user_id==UserRole.user_id',
                           secondaryjoin='Role.id==UserRole.role_id',
                           back_populates='users')
    warehouses = db.relationship('Warehouse', 
                                secondary='user_warehouse', 
                                primaryjoin='User.user_id==UserWarehouse.user_id',
                                secondaryjoin='Warehouse.warehouse_id==UserWarehouse.warehouse_id',
                                back_populates='users')
    agency = db.relationship('Agency', foreign_keys=[agency_id], backref='users')
    
    def get_id(self):
        """Override UserMixin get_id to use user_id instead of id"""
        return str(self.user_uuid or self.user_id)
    
    @property
    def is_locked(self):
        """Check if user account is currently locked"""
        if self.lock_until_at is None:
            return False
        from app.utils.timezone import now
        return now() < self.lock_until_at
    
    @property
    def last_login_dtime(self):
        """Alias for last_login_at for backward compatibility"""
        return self.last_login_at
    
    @property
    def password_changed_dtime(self):
        """Alias for password_changed_at for backward compatibility"""
        return self.password_changed_at
    
    @property
    def failed_login_attempts(self):
        """Alias for failed_login_count for backward compatibility"""
        return self.failed_login_count
    
    @property
    def last_login_ip(self):
        """IP address placeholder (not in database)"""
        return None
    
    
    @property
    def lockout_reason(self):
        """Lockout reason placeholder (not in database)"""
        return "Multiple failed login attempts" if self.failed_login_count > 5 else None

class Role(db.Model):
    """Role definitions for RBAC"""
    __tablename__ = 'role'
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=jamaica_now)
    
    users = db.relationship('User', 
                           secondary='user_role',
                           primaryjoin='Role.id==UserRole.role_id',
                           secondaryjoin='User.user_id==UserRole.user_id',
                           back_populates='roles')

class UserRole(db.Model):
    """User-Role assignment (many-to-many)"""
    __tablename__ = 'user_role'
    
    user_id = db.Column(db.Integer, db.ForeignKey('user.user_id'), primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey('role.id'), primary_key=True)
    assigned_at = db.Column(db.DateTime, default=jamaica_now)
    assigned_by = db.Column(db.Integer, db.ForeignKey('user.user_id'))
    create_by_id = db.Column(db.String(20), nullable=False, default='system')
    create_dtime = db.Column(db.DateTime, nullable=False, default=jamaica_now)
    update_by_id = db.Column(db.String(20), nullable=False, default='system')
    update_dtime = db.Column(db.DateTime, nullable=False, default=jamaica_now)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)

class Permission(db.Model):
    """Permission definitions for RBAC"""
    __tablename__ = 'permission'
    
    perm_id = db.Column(db.Integer, primary_key=True)
    resource = db.Column(db.String(50), nullable=False)
    action = db.Column(db.String(50), nullable=False)
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False, default=jamaica_now)
    update_by_id = db.Column(db.String(20), nullable=False)
    update_dtime = db.Column(db.DateTime, nullable=False, default=jamaica_now)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)

class RolePermission(db.Model):
    """Role-Permission assignment (many-to-many)"""
    __tablename__ = 'role_permission'
    
    role_id = db.Column(db.Integer, db.ForeignKey('role.id'), primary_key=True)
    perm_id = db.Column(db.Integer, db.ForeignKey('permission.perm_id'), primary_key=True)
    scope_json = db.Column(db.JSON)
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False, default=jamaica_now)
    update_by_id = db.Column(db.String(20), nullable=False)
    update_dtime = db.Column(db.DateTime, nullable=False, default=jamaica_now)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)

class UserWarehouse(db.Model):
    """User-Warehouse access control"""
    __tablename__ = 'user_warehouse'
    
    user_id = db.Column(db.Integer, db.ForeignKey('user.user_id'), primary_key=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouse.warehouse_id'), primary_key=True)
    assigned_at = db.Column(db.DateTime, default=jamaica_now)
    assigned_by = db.Column(db.Integer, db.ForeignKey('user.user_id'))

class Event(db.Model):
    """Disaster Event (from aidmgmt-3.sql)
    
    Event Types: STORM, HURRICANE, TORNADO, FLOOD, TSUNAMI, FIRE, EARTHQUAKE, WAR, EPIDEMIC, ADHOC
    Status Codes: A=Active, C=Closed
    """
    __tablename__ = 'event'
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('STORM','HURRICANE','TORNADO','FLOOD','TSUNAMI','FIRE','EARTHQUAKE','WAR','EPIDEMIC','ADHOC')",
            name='c_event_1'
        ),
        CheckConstraint('start_date <= CURRENT_DATE', name='c_event_2'),
        CheckConstraint("status_code IN ('A','C')", name='c_event_3'),
        CheckConstraint(
            "(status_code = 'A' AND closed_date IS NULL) OR (status_code = 'C' AND closed_date IS NOT NULL)",
            name='c_event_4a'
        ),
        CheckConstraint(
            "(reason_desc IS NULL AND closed_date IS NULL) OR (reason_desc IS NOT NULL AND closed_date IS NOT NULL)",
            name='c_event_4b'
        ),
    )
    
    event_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    event_type = db.Column(db.String(16), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    event_name = db.Column(db.String(60), nullable=False)
    event_desc = db.Column(db.String(255), nullable=False)
    impact_desc = db.Column(db.Text, nullable=False)
    status_code = db.Column(db.CHAR(1), nullable=False)
    closed_date = db.Column(db.Date)
    reason_desc = db.Column(db.String(255))
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False)
    update_by_id = db.Column(db.String(20), nullable=False)
    update_dtime = db.Column(db.DateTime, nullable=False)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)
    
    __mapper_args__ = {
        'version_id_col': version_nbr
    }

class Custodian(db.Model):
    """GOJ Agency (ODPEM)"""
    __tablename__ = 'custodian'
    
    custodian_id = db.Column(db.Integer, primary_key=True)
    custodian_name = db.Column(db.String(120), nullable=False, unique=True)
    address1_text = db.Column(db.String(255), nullable=False)
    address2_text = db.Column(db.String(255))
    parish_code = db.Column(db.CHAR(2), db.ForeignKey('parish.parish_code'), nullable=False)
    contact_name = db.Column(db.String(50), nullable=False)
    phone_no = db.Column(db.String(20), nullable=False)
    email_text = db.Column(db.String(100))
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False)
    update_by_id = db.Column(db.String(20), nullable=False)
    update_dtime = db.Column(db.DateTime, nullable=False)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)
    
    parish = db.relationship('Parish', backref='custodians')
    
    __mapper_args__ = {
        'version_id_col': version_nbr
    }

class Warehouse(db.Model):
    """Warehouse/Storage Location (from aidmgmt-3.sql)"""
    __tablename__ = 'warehouse'
    
    warehouse_id = db.Column(db.Integer, primary_key=True)
    warehouse_name = db.Column(db.Text, nullable=False)
    warehouse_type = db.Column(db.String(10), nullable=False)
    address1_text = db.Column(db.String(255), nullable=False)
    address2_text = db.Column(db.String(255))
    parish_code = db.Column(db.CHAR(2), db.ForeignKey('parish.parish_code'), nullable=False)
    contact_name = db.Column(db.String(50), nullable=False)
    phone_no = db.Column(db.String(20), nullable=False)
    email_text = db.Column(db.String(100))
    custodian_id = db.Column(db.Integer, db.ForeignKey('custodian.custodian_id'), nullable=False)
    status_code = db.Column(db.CHAR(1), nullable=False)
    reason_desc = db.Column(db.String(255))
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False)
    update_by_id = db.Column(db.String(20), nullable=False)
    update_dtime = db.Column(db.DateTime, nullable=False)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)
    
    parish = db.relationship('Parish', backref='warehouses')
    custodian = db.relationship('Custodian', backref='warehouses')
    users = db.relationship('User', 
                           secondary='user_warehouse',
                           primaryjoin='Warehouse.warehouse_id==UserWarehouse.warehouse_id',
                           secondaryjoin='User.user_id==UserWarehouse.user_id',
                           back_populates='warehouses')

class Agency(db.Model):
    """Agency (Request-only locations)"""
    __tablename__ = 'agency'
    
    agency_id = db.Column(db.Integer, primary_key=True)
    agency_name = db.Column(db.String(120), nullable=False, unique=True)
    agency_type = db.Column(db.String(16), nullable=False)
    address1_text = db.Column(db.String(255), nullable=False)
    address2_text = db.Column(db.String(255))
    parish_code = db.Column(db.CHAR(2), db.ForeignKey('parish.parish_code'), nullable=False)
    contact_name = db.Column(db.String(50), nullable=False)
    phone_no = db.Column(db.String(20), nullable=False)
    email_text = db.Column(db.String(100))
    ineligible_event_id = db.Column(db.Integer, db.ForeignKey('event.event_id'))
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouse.warehouse_id'))
    status_code = db.Column(db.CHAR(1), nullable=False)
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False)
    update_by_id = db.Column(db.String(20), nullable=False)
    update_dtime = db.Column(db.DateTime, nullable=False)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)
    
    parish = db.relationship('Parish', backref='agencies')
    ineligible_event = db.relationship('Event', backref='ineligible_agencies')
    warehouse = db.relationship('Warehouse', backref='agency', uselist=False)

class Parish(db.Model):
    """Jamaican Parish"""
    __tablename__ = 'parish'
    
    parish_code = db.Column(db.CHAR(2), primary_key=True)
    parish_name = db.Column(db.String(40), nullable=False)

class UnitOfMeasure(db.Model):
    """Unit of Measure (Master Data - CUSTODIAN role only)
    
    Defines units of measure for relief items and inventory tracking.
    Updated schema includes status_code and optimistic locking support.
    """
    __tablename__ = 'unitofmeasure'
    __table_args__ = {'extend_existing': True}
    
    uom_code = db.Column(db.String(25), primary_key=True)
    uom_desc = db.Column(db.String(60), nullable=False)
    comments_text = db.Column(db.Text)
    status_code = db.Column(db.CHAR(1), nullable=False, default='A')
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False)
    update_by_id = db.Column(db.String(20), nullable=False)
    update_dtime = db.Column(db.DateTime, nullable=False)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)
    
    __mapper_args__ = {
        'version_id_col': version_nbr
    }

class ItemCategory(db.Model):
    """Item Category (Master Data - CUSTODIAN role only)
    
    Defines categories for relief items with identity PK and unique category codes.
    Updated schema with category_id as primary key instead of category_code.
    Supports GOODS and FUNDS category types for donation classification.
    """
    __tablename__ = 'itemcatg'
    __table_args__ = {'extend_existing': True}
    
    category_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    category_type = db.Column(db.CHAR(5), nullable=False, default='GOODS')
    category_code = db.Column(db.String(30), nullable=False, unique=True)
    category_desc = db.Column(db.String(60), nullable=False)
    comments_text = db.Column(db.Text)
    status_code = db.Column(db.CHAR(1), nullable=False)
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False)
    update_by_id = db.Column(db.String(20), nullable=False)
    update_dtime = db.Column(db.DateTime, nullable=False)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)
    
    __mapper_args__ = {
        'version_id_col': version_nbr
    }

class Item(db.Model):
    """Relief Item (from aidmgmt-3.sql)
    
    Updated schema with new columns: item_code, units_size_vary_flag, 
    is_batched_flag, can_expire_flag, issuance_order.
    Removed obsolete columns: category_code, expiration_apply_flag.
    """
    __tablename__ = 'item'
    __table_args__ = {'extend_existing': True}
    
    item_id = db.Column(db.Integer, primary_key=True)
    item_code = db.Column(db.String(16), nullable=False, unique=True)
    item_name = db.Column(db.String(60), nullable=False, unique=True)
    sku_code = db.Column(db.String(30), nullable=False, unique=True)
    category_id = db.Column(db.Integer, db.ForeignKey('itemcatg.category_id'), nullable=False)
    item_desc = db.Column(db.Text, nullable=False)
    reorder_qty = db.Column(db.Numeric(12, 2), nullable=False)
    default_uom_code = db.Column(db.String(25), db.ForeignKey('unitofmeasure.uom_code'), nullable=False)
    units_size_vary_flag = db.Column(db.Boolean, nullable=False, default=False)
    usage_desc = db.Column(db.Text)
    storage_desc = db.Column(db.Text)
    is_batched_flag = db.Column(db.Boolean, nullable=False, default=True)
    can_expire_flag = db.Column(db.Boolean, nullable=False, default=False)
    issuance_order = db.Column(db.String(20), nullable=False, default='FIFO')
    comments_text = db.Column(db.Text)
    status_code = db.Column(db.CHAR(1), nullable=False)
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False)
    update_by_id = db.Column(db.String(20), nullable=False)
    update_dtime = db.Column(db.DateTime, nullable=False)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)
    
    category = db.relationship('ItemCategory', foreign_keys=[category_id], backref='items')
    default_uom = db.relationship('UnitOfMeasure', backref='items')
    
    __mapper_args__ = {
        'version_id_col': version_nbr
    }

class ItemCostDef(db.Model):
    """Item Cost Definition - Defines cost types for items
    
    Defines various cost types that can be associated with items:
    - Purchase costs: Purchase Price, CIF, etc.
    - Additional costs: Storage, Transport, Inspection, Intake, Warehousing, etc.
    
    Cost types are categorized as PURCHASE or ADDITIONAL.
    
    Status Codes:
        A = Active
        I = Inactive
    """
    __tablename__ = 'itemcostdef'
    
    cost_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    cost_name = db.Column(db.String(50), nullable=False, unique=True)
    cost_desc = db.Column(db.String(255), nullable=False)
    cost_type = db.Column(db.CHAR(16), nullable=False)
    status_code = db.Column(db.CHAR(1), nullable=False)
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False)
    update_by_id = db.Column(db.String(20), nullable=False)
    update_dtime = db.Column(db.DateTime, nullable=False)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)
    
    __table_args__ = (
        db.CheckConstraint("length(cost_name) <= 50", name='c_itemcostdef_1'),
        db.CheckConstraint("cost_type IN ('PURCHASE','ADDITIONAL')", name='c_itemcostdef_2'),
        db.CheckConstraint("status_code IN ('A','I')", name='c_itemcostdef_3'),
    )
    
    __mapper_args__ = {
        'version_id_col': version_nbr
    }

class Inventory(db.Model):
    """Inventory - Warehouse-level stock tracking with composite PK
    
    inventory_id IS the warehouse_id - named for table alignment.
    Composite primary key (inventory_id, item_id) ensures one record per item per warehouse.
    """
    __tablename__ = 'inventory'
    
    inventory_id = db.Column(db.Integer, db.ForeignKey('warehouse.warehouse_id'), primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('item.item_id'), primary_key=True)
    usable_qty = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    reserved_qty = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    defective_qty = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    expired_qty = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    uom_code = db.Column(db.String(25), db.ForeignKey('unitofmeasure.uom_code'), nullable=False)
    last_verified_by = db.Column(db.String(20))
    last_verified_date = db.Column(db.Date)
    status_code = db.Column(db.CHAR(1), nullable=False)
    comments_text = db.Column(db.Text)
    reorder_qty = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False)
    update_by_id = db.Column(db.String(20), nullable=False)
    update_dtime = db.Column(db.DateTime, nullable=False)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)
    
    warehouse = db.relationship('Warehouse', foreign_keys=[inventory_id], backref='inventories')
    item = db.relationship('Item', backref='inventories')
    uom = db.relationship('UnitOfMeasure', backref='inventories')
    
    __mapper_args__ = {
        'version_id_col': version_nbr
    }

class ItemBatch(db.Model):
    """Item Batch - Tracks batches of items in inventory for FEFO/FIFO allocation
    
    Supports batch-level inventory management with expiry tracking and
    allocation rules based on item configuration (is_batched_flag, can_expire_flag, issuance_order).
    """
    __tablename__ = 'itembatch'
    __table_args__ = {'extend_existing': True}
    
    batch_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    inventory_id = db.Column(db.Integer, db.ForeignKey('inventory.inventory_id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('item.item_id'), nullable=False)
    batch_no = db.Column(db.String(20), nullable=True)
    batch_date = db.Column(db.Date, nullable=True)
    expiry_date = db.Column(db.Date)
    usable_qty = db.Column(db.Numeric(15, 4), nullable=False, default=0)
    reserved_qty = db.Column(db.Numeric(15, 4), nullable=False, default=0)
    defective_qty = db.Column(db.Numeric(15, 4), nullable=False, default=0)
    expired_qty = db.Column(db.Numeric(15, 4), nullable=False, default=0)
    uom_code = db.Column(db.String(25), db.ForeignKey('unitofmeasure.uom_code'), nullable=False)
    size_spec = db.Column(db.String(30))
    avg_unit_value = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    last_verified_by = db.Column(db.String(20))
    last_verified_date = db.Column(db.Date)
    status_code = db.Column(db.CHAR(1), nullable=False, default='A')
    comments_text = db.Column(db.Text)
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False)
    update_by_id = db.Column(db.String(20), nullable=False)
    update_dtime = db.Column(db.DateTime, nullable=False)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)
    
    # Relationship to Inventory with composite foreign key
    inventory = db.relationship('Inventory', 
        foreign_keys=[inventory_id, item_id],
        primaryjoin='and_(ItemBatch.inventory_id==Inventory.inventory_id, ItemBatch.item_id==Inventory.item_id)',
        backref=backref('batches', overlaps='batches,item'),
        overlaps='batches,item')
    item = db.relationship('Item', 
        backref=backref('batches', overlaps='batches,inventory'),
        overlaps='batches,inventory')
    uom = db.relationship('UnitOfMeasure', backref='batches')
    
    __mapper_args__ = {
        'version_id_col': version_nbr
    }
    
    @property
    def available_qty(self):
        """Calculate available quantity for allocation (usable - reserved)"""
        return self.usable_qty - self.reserved_qty
    
    @property
    def is_expired(self):
        """Check if batch is expired"""
        if not self.expiry_date:
            return False
        from datetime import date
        return self.expiry_date < date.today()

class BatchLocation(db.Model):
    """Batch Location - Tracks physical locations of batches within warehouses
    
    Junction table linking batches to specific bin/shelf locations for
    precise warehouse management and stock locating.
    """
    __tablename__ = 'batchlocation'
    __table_args__ = (
        db.ForeignKeyConstraint(
            ['inventory_id', 'batch_id'],
            ['itembatch.inventory_id', 'itembatch.batch_id']
        ),
        {'extend_existing': True}
    )
    
    inventory_id = db.Column(db.Integer, db.ForeignKey('warehouse.warehouse_id'), primary_key=True, nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey('location.location_id'), primary_key=True, nullable=False)
    batch_id = db.Column(db.Integer, db.ForeignKey('itembatch.batch_id'), primary_key=True, nullable=False)
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False)
    
    batch = db.relationship('ItemBatch', foreign_keys=[batch_id], backref='locations')
    location = db.relationship('Location', backref='batch_locations')

class Currency(db.Model):
    """Currency Lookup Table"""
    __tablename__ = 'currency'
    
    currency_code = db.Column(db.String(10), primary_key=True)
    currency_name = db.Column(db.String(60), nullable=False)
    currency_sign = db.Column(db.String(6), nullable=False)
    status_code = db.Column(db.CHAR(1), nullable=False)
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False)
    update_by_id = db.Column(db.String(20), nullable=False)
    update_dtime = db.Column(db.DateTime, nullable=False)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)
    
    __mapper_args__ = {
        'version_id_col': version_nbr
    }

class Country(db.Model):
    """Country Lookup Table"""
    __tablename__ = 'country'
    
    country_id = db.Column(db.SmallInteger, primary_key=True)
    country_name = db.Column(db.String(80), nullable=False)
    currency_code = db.Column(db.String(10), db.ForeignKey('currency.currency_code'), nullable=False)
    status_code = db.Column(db.CHAR(1), nullable=False)
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False)
    update_by_id = db.Column(db.String(20), nullable=False)
    update_dtime = db.Column(db.DateTime, nullable=False)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)
    
    currency = db.relationship('Currency', backref='countries')
    
    __mapper_args__ = {
        'version_id_col': version_nbr
    }

class Donor(db.Model):
    """Donor"""
    __tablename__ = 'donor'
    
    donor_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    donor_code = db.Column(db.String(16), nullable=False)
    donor_name = db.Column(db.String(255), nullable=False, unique=True)
    org_type_desc = db.Column(db.String(30))
    address1_text = db.Column(db.String(255), nullable=False)
    address2_text = db.Column(db.String(255))
    country_id = db.Column(db.SmallInteger, db.ForeignKey('country.country_id'), nullable=False, default=388)
    phone_no = db.Column(db.String(20), nullable=False)
    email_text = db.Column(db.String(100))
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False)
    update_by_id = db.Column(db.String(20), nullable=False)
    update_dtime = db.Column(db.DateTime, nullable=False)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)
    
    country = db.relationship('Country', backref='donors')

class Donation(db.Model):
    """Donation
    
    Tracks donations received from donors for specific events.
    Includes cost breakdown for items, storage, haulage, and other expenses.
    
    Status Codes:
        E = Entered (initial entry)
        V = Verified (verified by custodian)
        P = Processed (donation intake completed)
    """
    __tablename__ = 'donation'
    
    donation_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    donor_id = db.Column(db.Integer, db.ForeignKey('donor.donor_id'), nullable=False)
    donation_desc = db.Column(db.Text, nullable=False)
    origin_country_id = db.Column(db.SmallInteger, db.ForeignKey('country.country_id'), nullable=False)
    origin_address1_text = db.Column(db.String(255))
    origin_address2_text = db.Column(db.String(255))
    event_id = db.Column(db.Integer, db.ForeignKey('event.event_id'), nullable=False)
    custodian_id = db.Column(db.Integer, db.ForeignKey('custodian.custodian_id'), nullable=False)
    received_date = db.Column(db.Date, nullable=False)
    tot_item_cost = db.Column(db.Numeric(12, 2), nullable=False, default=0.00)
    storage_cost = db.Column(db.Numeric(12, 2), nullable=False, default=0.00)
    haulage_cost = db.Column(db.Numeric(12, 2), nullable=False, default=0.00)
    other_cost = db.Column(db.Numeric(12, 2), nullable=False, default=0.00)
    other_cost_desc = db.Column(db.String(255))
    status_code = db.Column(db.CHAR(1), nullable=False)
    comments_text = db.Column(db.Text)
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False)
    update_by_id = db.Column(db.String(20), nullable=False)
    update_dtime = db.Column(db.DateTime, nullable=False)
    verify_by_id = db.Column(db.String(20), nullable=True)
    verify_dtime = db.Column(db.DateTime, nullable=True)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)
    
    __table_args__ = (
        db.CheckConstraint("received_date <= CURRENT_DATE", name='c_donation_1'),
        db.CheckConstraint("tot_item_cost >= 0.00", name='c_donation_2'),
        db.CheckConstraint("storage_cost >= 0.00", name='c_donation_2a'),
        db.CheckConstraint("haulage_cost >= 0.00", name='c_donation_2b'),
        db.CheckConstraint("other_cost >= 0.00", name='c_donation_2c'),
        db.CheckConstraint("status_code IN ('E', 'V', 'P')", name='c_donation_3'),
    )
    
    donor = db.relationship('Donor', backref='donations')
    event = db.relationship('Event', backref='donations')
    custodian = db.relationship('Custodian', backref='donations')
    origin_country = db.relationship('Country', backref='donations')
    created_by = db.relationship('User', foreign_keys=[create_by_id], primaryjoin='Donation.create_by_id == User.user_name', backref='donations_created')
    verify_by = db.relationship('User', foreign_keys=[verify_by_id], primaryjoin='Donation.verify_by_id == User.user_name', backref='donations_verified')
    update_by = db.relationship('User', foreign_keys=[update_by_id], primaryjoin='Donation.update_by_id == User.user_name', backref='donations_updated')
    
    __mapper_args__ = {
        'version_id_col': version_nbr
    }

class DonationItem(db.Model):
    """Donation Item - Items donated in a donation
    
    Tracks individual items and quantities donated as part of a donation.
    Links donations to specific items with verification status.
    
    Donation Types:
        GOODS = Physical goods (requires uom_code, no currency_code)
        FUNDS = Monetary donation (requires currency_code, no uom_code)
    
    Status Codes:
        P = Processed
        V = Verified
    """
    __tablename__ = 'donation_item'
    
    donation_id = db.Column(db.Integer, db.ForeignKey('donation.donation_id'), primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('item.item_id'), primary_key=True)
    donation_type = db.Column(db.CHAR(5), nullable=False, default='GOODS')
    item_qty = db.Column(db.Numeric(9, 2), nullable=False, default=1.00)
    item_cost = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    uom_code = db.Column(db.String(25), db.ForeignKey('unitofmeasure.uom_code'), nullable=True)
    currency_code = db.Column(db.String(10), db.ForeignKey('currency.currency_code'), nullable=True)
    location_name = db.Column(db.Text, nullable=False)
    status_code = db.Column(db.CHAR(1), nullable=False, default='V')
    comments_text = db.Column(db.Text)
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False)
    update_by_id = db.Column(db.String(20), nullable=False, default='SYSTEM')
    update_dtime = db.Column(db.DateTime, nullable=False, server_default=db.text('CURRENT_TIMESTAMP'))
    verify_by_id = db.Column(db.String(20), nullable=True)
    verify_dtime = db.Column(db.DateTime, nullable=True)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)
    
    __table_args__ = (
        db.CheckConstraint("donation_type IN ('GOODS', 'FUNDS')", name='c_donation_item_0'),
        db.CheckConstraint("item_qty >= 0.00", name='c_donation_item_1a'),
        db.CheckConstraint("item_cost >= 0.00", name='c_donation_item_1b'),
        db.CheckConstraint("status_code IN ('P', 'V')", name='c_donation_item_2'),
        db.CheckConstraint(
            "(donation_type = 'GOODS' AND uom_code IS NOT NULL AND currency_code IS NULL) OR "
            "(donation_type = 'FUNDS' AND currency_code IS NOT NULL AND uom_code IS NULL)",
            name='c_donation_item_type_fields'
        ),
    )
    
    donation = db.relationship('Donation', backref='items')
    item = db.relationship('Item', backref='donation_items')
    uom = db.relationship('UnitOfMeasure', backref='donation_items')
    currency = db.relationship('Currency', backref='donation_items')
    
    __mapper_args__ = {
        'version_id_col': version_nbr
    }

class DonationDoc(db.Model):
    """Donation Document - Attachments for donations
    
    Tracks documents attached to donations (receipts, manifests, delivery notices).
    Supports PDF and JPEG file formats.
    """
    __tablename__ = 'donation_doc'
    
    document_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    donation_id = db.Column(db.Integer, db.ForeignKey('donation.donation_id'), nullable=False)
    document_type = db.Column(db.String(40), nullable=False)
    document_desc = db.Column(db.String(255), nullable=False)
    file_name = db.Column(db.String(80), nullable=False)
    file_type = db.Column(db.String(30), nullable=False)
    file_size = db.Column(db.String(20))
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False)
    update_by_id = db.Column(db.String(20), nullable=False)
    update_dtime = db.Column(db.DateTime, nullable=False)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)
    
    __table_args__ = (
        db.CheckConstraint("file_type IN ('application/pdf', 'image/jpeg')", name='c_donation_doc_1'),
    )
    
    donation = db.relationship('Donation', backref='documents')
    
    __mapper_args__ = {
        'version_id_col': version_nbr
    }

class ReliefRqstStatus(db.Model):
    """Relief Request Status Lookup Table
    
    Status Codes:
        0 = DRAFT (creation workflow)
        1 = AWAITING APPROVAL (creation workflow)
        2 = CANCELLED (creation workflow)
        3 = SUBMITTED (creation workflow)
        4 = DENIED (action workflow, requires reason)
        5 = PART FILLED (action workflow)
        6 = CLOSED (action workflow, requires reason)
        7 = FILLED (action workflow)
        8 = INELIGIBLE (action workflow, requires reason)
        9 = PROCESSED (processed workflow)
    
    Views:
        v_status4reliefrqst_create: Statuses 0,1,2,3 (creation)
        v_status4reliefrqst_action: Statuses 4,5,6,7,8 (action)
        v_status4reliefrqst_processed: Status 9 (processed)
    """
    __tablename__ = 'reliefrqst_status'
    
    status_code = db.Column(db.SmallInteger, primary_key=True)
    status_desc = db.Column(db.String(30), nullable=False)
    reason_rqrd_flag = db.Column(db.Boolean, nullable=False, default=False)
    is_active_flag = db.Column(db.Boolean, nullable=False, default=True)

class ReliefRqstItemStatus(db.Model):
    """Relief Request Item Status Lookup Table"""
    __tablename__ = 'reliefrqstitem_status'
    
    status_code = db.Column(db.CHAR(1), primary_key=True)
    status_desc = db.Column(db.String(30), nullable=False)
    item_qty_rule = db.Column(db.CHAR(2), nullable=False)
    active_flag = db.Column(db.Boolean, nullable=False, default=True)
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False)
    update_by_id = db.Column(db.String(20), nullable=False)
    update_dtime = db.Column(db.DateTime, nullable=False)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)

class ReliefRqst(db.Model):
    """Relief Request / Needs List (AIDMGMT workflow)"""
    __tablename__ = 'reliefrqst'
    
    reliefrqst_id = db.Column(db.Integer, primary_key=True)
    agency_id = db.Column(db.Integer, db.ForeignKey('agency.agency_id'), nullable=False)
    request_date = db.Column(db.Date, nullable=False)
    tracking_no = db.Column(db.String(7), nullable=False, server_default=db.text("upper(substr(replace((gen_random_uuid())::text, '-'::text, ''::text), 1, 7))"))
    eligible_event_id = db.Column(db.Integer, db.ForeignKey('event.event_id'))
    urgency_ind = db.Column(db.CHAR(1), nullable=False)
    rqst_notes_text = db.Column(db.Text)
    review_notes_text = db.Column(db.Text)
    status_code = db.Column(db.SmallInteger, db.ForeignKey('reliefrqst_status.status_code'), nullable=False, default=0)
    status_reason_desc = db.Column(db.String(255))
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False)
    review_by_id = db.Column(db.String(20))
    review_dtime = db.Column(db.DateTime)
    action_by_id = db.Column(db.String(20))
    action_dtime = db.Column(db.DateTime)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)
    
    agency = db.relationship('Agency', backref='relief_requests')
    eligible_event = db.relationship('Event', backref='eligible_relief_requests')
    status = db.relationship('ReliefRqstStatus', backref='relief_requests')

class ReliefRqstItem(db.Model):
    """Relief Request Item"""
    __tablename__ = 'reliefrqst_item'
    
    reliefrqst_id = db.Column(db.Integer, db.ForeignKey('reliefrqst.reliefrqst_id'), primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('item.item_id'), primary_key=True)
    request_qty = db.Column(db.Numeric(12, 2), nullable=False)
    issue_qty = db.Column(db.Numeric(12, 2), nullable=False)
    urgency_ind = db.Column(db.CHAR(1), nullable=False)
    rqst_reason_desc = db.Column(db.String(255))
    required_by_date = db.Column(db.Date)
    status_code = db.Column(db.CHAR(1), db.ForeignKey('reliefrqstitem_status.status_code'), nullable=False, server_default='R')
    status_reason_desc = db.Column(db.String(255))
    action_by_id = db.Column(db.String(20))
    action_dtime = db.Column(db.DateTime)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)
    
    relief_request = db.relationship('ReliefRqst', backref='items')
    item = db.relationship('Item', backref='request_items')
    item_status = db.relationship('ReliefRqstItemStatus', backref='request_items')

class ReliefRequestFulfillmentLock(db.Model):
    """Fulfillment lock to ensure single fulfiller per relief request"""
    __tablename__ = 'relief_request_fulfillment_lock'
    
    reliefrqst_id = db.Column(db.Integer, db.ForeignKey('reliefrqst.reliefrqst_id', ondelete='CASCADE'), primary_key=True)
    fulfiller_user_id = db.Column(db.Integer, db.ForeignKey('user.user_id', ondelete='CASCADE'), nullable=False)
    fulfiller_email = db.Column(db.String(100), nullable=False)
    acquired_at = db.Column(db.DateTime, nullable=False, default=jamaica_now)
    expires_at = db.Column(db.DateTime)
    
    relief_request = db.relationship('ReliefRqst', backref=db.backref('fulfillment_lock', uselist=False))
    fulfiller = db.relationship('User', backref='fulfillment_locks')

class ReliefPkg(db.Model):
    """Relief Package / Fulfilment (AIDMGMT workflow)
    
    Tracks relief packages prepared for distribution to agencies.
    Each package contains items allocated from inventory for a specific relief request.
    
    Status Codes:
        A = Draft (package being prepared)
        P = Processing (items being packed)
        C = Completed (packaging finished)
        V = Verified (package verified by custodian)
        D = Dispatched (package sent to agency)
        R = Received (package received by agency)
    """
    __tablename__ = 'reliefpkg'
    
    reliefpkg_id = db.Column(db.Integer, primary_key=True)
    agency_id = db.Column(db.Integer, db.ForeignKey('agency.agency_id'), nullable=False)
    tracking_no = db.Column(db.CHAR(7), nullable=False)
    eligible_event_id = db.Column(db.Integer, db.ForeignKey('event.event_id'))
    to_inventory_id = db.Column(db.Integer, db.ForeignKey('warehouse.warehouse_id'), nullable=False)
    reliefrqst_id = db.Column(db.Integer, db.ForeignKey('reliefrqst.reliefrqst_id'), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    dispatch_dtime = db.Column(db.DateTime)
    transport_mode = db.Column(db.String(255))
    comments_text = db.Column(db.String(255))
    status_code = db.Column(db.CHAR(1), nullable=False)
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False)
    update_by_id = db.Column(db.String(20), nullable=False)
    update_dtime = db.Column(db.DateTime)
    verify_by_id = db.Column(db.String(20), nullable=False)
    verify_dtime = db.Column(db.DateTime)
    received_by_id = db.Column(db.String(20), nullable=False)
    received_dtime = db.Column(db.DateTime)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)
    
    __table_args__ = (
        db.CheckConstraint("start_date <= CURRENT_DATE", name='c_reliefpkg_1'),
        db.CheckConstraint("(dispatch_dtime IS NULL AND status_code != 'D') OR (dispatch_dtime IS NOT NULL AND status_code = 'D')", name='c_reliefpkg_2'),
        db.CheckConstraint("status_code IN ('A','P','C','V','D','R')", name='c_reliefpkg_3'),
    )
    
    agency = db.relationship('Agency', backref='relief_packages')
    eligible_event = db.relationship('Event', backref='relief_packages')
    relief_request = db.relationship('ReliefRqst', backref='packages')
    to_inventory = db.relationship('Warehouse', foreign_keys=[to_inventory_id], backref='relief_packages')
    
    __mapper_args__ = {
        'version_id_col': version_nbr
    }

class ReliefPkgItem(db.Model):
    """Relief Package Item - Batch-level allocation for relief packages
    
    All relief package allocations are done at the batch level, ensuring full
    traceability and FEFO/FIFO compliance. Each allocation references a specific
    batch in the source inventory.
    """
    __tablename__ = 'reliefpkg_item'
    __table_args__ = (
        db.ForeignKeyConstraint(
            ['fr_inventory_id', 'batch_id', 'item_id'],
            ['itembatch.inventory_id', 'itembatch.batch_id', 'itembatch.item_id']
        ),
        {'extend_existing': True}
    )
    
    reliefpkg_id = db.Column(db.Integer, db.ForeignKey('reliefpkg.reliefpkg_id'), primary_key=True)
    fr_inventory_id = db.Column(db.Integer, primary_key=True, nullable=False)
    batch_id = db.Column(db.Integer, primary_key=True, nullable=False)
    item_id = db.Column(db.Integer, primary_key=True, nullable=False)
    item_qty = db.Column(db.Numeric(15, 4), nullable=False)
    uom_code = db.Column(db.String(25), db.ForeignKey('unitofmeasure.uom_code'), nullable=False)
    reason_text = db.Column(db.String(255))
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False)
    update_by_id = db.Column(db.String(20), nullable=False)
    update_dtime = db.Column(db.DateTime, nullable=False)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)
    
    package = db.relationship('ReliefPkg', backref='items')
    item = db.relationship('Item', 
                          primaryjoin='ReliefPkgItem.item_id==Item.item_id',
                          foreign_keys=[item_id],
                          backref='package_items')
    batch = db.relationship('ItemBatch',
                           primaryjoin='and_(ReliefPkgItem.fr_inventory_id==ItemBatch.inventory_id, ReliefPkgItem.batch_id==ItemBatch.batch_id, ReliefPkgItem.item_id==ItemBatch.item_id)',
                           foreign_keys=[fr_inventory_id, batch_id, item_id],
                           overlaps="item,package_items",
                           backref=db.backref('package_items', overlaps="item,package_items"))
    uom = db.relationship('UnitOfMeasure', backref='package_items')
    
    __mapper_args__ = {
        'version_id_col': version_nbr
    }

class DBIntake(db.Model):
    """Distribution/Donation Intake (AIDMGMT workflow step 3)"""
    __tablename__ = 'dbintake'
    
    reliefpkg_id = db.Column(db.Integer, db.ForeignKey('reliefpkg.reliefpkg_id'), primary_key=True)
    inventory_id = db.Column(db.Integer, db.ForeignKey('inventory.inventory_id'), primary_key=True)
    intake_date = db.Column(db.Date, nullable=False)
    comments_text = db.Column(db.String(255))
    status_code = db.Column(db.CHAR(1), nullable=False)
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False)
    update_by_id = db.Column(db.String(20), nullable=False)
    update_dtime = db.Column(db.DateTime)
    verify_by_id = db.Column(db.String(20))
    verify_dtime = db.Column(db.DateTime)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)
    
    package = db.relationship('ReliefPkg', backref='intake_records')
    inventory = db.relationship('Inventory', backref='intake_records')

class DBIntakeItem(db.Model):
    """Distribution/Donation Intake Item"""
    __tablename__ = 'dbintake_item'
    __table_args__ = (
        db.ForeignKeyConstraint(
            ['reliefpkg_id', 'inventory_id'],
            ['dbintake.reliefpkg_id', 'dbintake.inventory_id']
        ),
    )
    
    reliefpkg_id = db.Column(db.Integer, primary_key=True)
    inventory_id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('item.item_id'), primary_key=True)
    usable_qty = db.Column(db.Numeric(12, 2), nullable=False)
    location1_id = db.Column(db.Integer, db.ForeignKey('location.location_id'))
    defective_qty = db.Column(db.Numeric(12, 2), nullable=False)
    location2_id = db.Column(db.Integer, db.ForeignKey('location.location_id'))
    expired_qty = db.Column(db.Numeric(12, 2), nullable=False)
    location3_id = db.Column(db.Integer, db.ForeignKey('location.location_id'))
    uom_code = db.Column(db.String(25), db.ForeignKey('unitofmeasure.uom_code'), nullable=False)
    status_code = db.Column(db.CHAR(1), nullable=False)
    comments_text = db.Column(db.String(255))
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False)
    update_by_id = db.Column(db.String(20), nullable=False)
    update_dtime = db.Column(db.DateTime, nullable=False)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)
    
    item = db.relationship('Item',
                          primaryjoin='DBIntakeItem.item_id==Item.item_id',
                          foreign_keys=[item_id],
                          backref='intake_items')

class DistributionPackage(db.Model):
    """DRIMS Distribution Package (Alternative workflow)"""
    __tablename__ = 'distribution_package'
    
    id = db.Column(db.Integer, primary_key=True)
    package_number = db.Column(db.String(64), unique=True, nullable=False)
    recipient_agency_id = db.Column(db.Integer, db.ForeignKey('agency.agency_id'), nullable=False)
    assigned_warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouse.warehouse_id'))
    event_id = db.Column(db.Integer, db.ForeignKey('event.event_id'))
    status = db.Column(db.String(50), default='Draft', nullable=False)
    is_partial = db.Column(db.Boolean, default=False, nullable=False)
    created_by = db.Column(db.String(200), nullable=False)
    approved_by = db.Column(db.String(200))
    approved_at = db.Column(db.DateTime)
    dispatched_by = db.Column(db.String(200))
    dispatched_at = db.Column(db.DateTime)
    delivered_at = db.Column(db.DateTime)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=jamaica_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=jamaica_now, nullable=False)
    
    agency = db.relationship('Agency', backref='distribution_packages')
    warehouse = db.relationship('Warehouse', backref='distribution_packages')
    event = db.relationship('Event', backref='distribution_packages')

class DistributionPackageItem(db.Model):
    """DRIMS Distribution Package Item"""
    __tablename__ = 'distribution_package_item'
    
    id = db.Column(db.Integer, primary_key=True)
    package_id = db.Column(db.Integer, db.ForeignKey('distribution_package.id', ondelete='CASCADE'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('item.item_id'), nullable=False)
    quantity = db.Column(db.Numeric(12, 2), nullable=False)
    notes = db.Column(db.Text)
    
    package = db.relationship('DistributionPackage', backref='items')
    item = db.relationship('Item', backref='distribution_package_items')

class Transfer(db.Model):
    """Transfer between warehouses
    
    Tracks inventory transfers between warehouses with batch-level detail.
    Foreign keys reference warehouse directly (fr_inventory_id and to_inventory_id
    are conceptually inventory IDs but reference warehouse.warehouse_id).
    
    Status Codes:
        D = Draft (transfer being prepared)
        C = Completed (transfer executed)
        V = Verified (transfer verified at destination)
        P = Processed (transfer intake completed)
    """
    __tablename__ = 'transfer'
    
    transfer_id = db.Column(db.Integer, primary_key=True)
    fr_inventory_id = db.Column(db.Integer, db.ForeignKey('warehouse.warehouse_id'), nullable=False)
    to_inventory_id = db.Column(db.Integer, db.ForeignKey('warehouse.warehouse_id'), nullable=False)
    eligible_event_id = db.Column(db.Integer, db.ForeignKey('event.event_id'))
    transfer_date = db.Column(db.Date, nullable=False, server_default=db.text('CURRENT_DATE'))
    reason_text = db.Column(db.String(255))
    status_code = db.Column(db.CHAR(1), nullable=False)
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False)
    update_by_id = db.Column(db.String(20), nullable=False)
    update_dtime = db.Column(db.DateTime)
    verify_by_id = db.Column(db.String(20), nullable=False)
    verify_dtime = db.Column(db.DateTime)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)
    
    __table_args__ = (
        db.CheckConstraint("transfer_date <= CURRENT_DATE", name='c_transfer_1'),
        db.CheckConstraint("status_code IN ('D', 'C', 'V', 'P')", name='c_transfer_2'),
        db.Index('dk_transfer_1', 'transfer_date'),
        db.Index('dk_transfer_2', 'fr_inventory_id'),
        db.Index('dk_transfer_3', 'to_inventory_id'),
    )
    
    from_warehouse = db.relationship('Warehouse', foreign_keys=[fr_inventory_id], backref='transfers_sent')
    to_warehouse = db.relationship('Warehouse', foreign_keys=[to_inventory_id], backref='transfers_received')
    event = db.relationship('Event', foreign_keys=[eligible_event_id], backref='transfers')

class TransferItem(db.Model):
    """Transfer Item - Batch-level transfer tracking between warehouses
    
    Tracks items being transferred from specific batches in source inventory.
    When received at destination, if batch doesn't exist, create it with zero
    quantities, then increment by received amounts. This preserves batch
    traceability across warehouse transfers.
    """
    __tablename__ = 'transfer_item'
    __table_args__ = (
        db.ForeignKeyConstraint(['inventory_id', 'item_id'], ['inventory.inventory_id', 'inventory.item_id']),
        db.ForeignKeyConstraint(['inventory_id', 'batch_id'], ['itembatch.inventory_id', 'itembatch.batch_id']),
        {'extend_existing': True}
    )
    
    transfer_id = db.Column(db.Integer, db.ForeignKey('transfer.transfer_id'), primary_key=True)
    item_id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, primary_key=True, nullable=False)
    inventory_id = db.Column(db.Integer, nullable=False)
    item_qty = db.Column(db.Numeric(15, 4), nullable=False)
    uom_code = db.Column(db.String(25), db.ForeignKey('unitofmeasure.uom_code'), nullable=False)
    reason_text = db.Column(db.String(255))
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False)
    update_by_id = db.Column(db.String(20), nullable=False)
    update_dtime = db.Column(db.DateTime, nullable=False)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)
    
    transfer = db.relationship('Transfer', backref='items')
    item = db.relationship('Item',
                          primaryjoin='TransferItem.item_id==Item.item_id',
                          foreign_keys=[item_id],
                          backref='transfer_items')
    batch = db.relationship('ItemBatch',
                           primaryjoin='and_(TransferItem.inventory_id==ItemBatch.inventory_id, TransferItem.batch_id==ItemBatch.batch_id)',
                           foreign_keys=[inventory_id, batch_id],
                           overlaps="item,transfer_items")
    uom = db.relationship('UnitOfMeasure', backref='transfer_items')
    
    __mapper_args__ = {
        'version_id_col': version_nbr
    }

class TransferRequest(db.Model):
    """Transfer request workflow (DRIMS extension)"""
    __tablename__ = 'transfer_request'
    
    id = db.Column(db.Integer, primary_key=True)
    from_warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouse.warehouse_id'), nullable=False)
    to_warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouse.warehouse_id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('item.item_id'), nullable=False)
    quantity = db.Column(db.Numeric(12,2), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='PENDING')
    requested_by = db.Column(db.Integer, db.ForeignKey('user.user_id'))
    requested_at = db.Column(db.DateTime, nullable=False, default=jamaica_now)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('user.user_id'))
    reviewed_at = db.Column(db.DateTime)
    notes = db.Column(db.Text)
    
    from_warehouse = db.relationship('Warehouse', foreign_keys=[from_warehouse_id])
    to_warehouse = db.relationship('Warehouse', foreign_keys=[to_warehouse_id])
    item = db.relationship('Item')
    requester = db.relationship('User', foreign_keys=[requested_by])
    reviewer = db.relationship('User', foreign_keys=[reviewed_by])

class Location(db.Model):
    """Bin/shelf locations within inventory (AIDMGMT schema)"""
    __tablename__ = 'location'
    
    location_id = db.Column(db.Integer, primary_key=True)
    inventory_id = db.Column(db.Integer, db.ForeignKey('inventory.inventory_id'), nullable=False)
    location_desc = db.Column(db.String(100), nullable=False)
    status_code = db.Column(db.CHAR(1), nullable=False)
    comments_text = db.Column(db.String(255))
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False)
    update_by_id = db.Column(db.String(20), nullable=False)
    update_dtime = db.Column(db.DateTime, nullable=False)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)
    
    __mapper_args__ = {'version_id_col': version_nbr}
    
    inventory = db.relationship('Inventory', backref='locations')

class ItemLocation(db.Model):
    """Item locations within inventory - tracks items at specific bin/shelf locations (AIDMGMT)"""
    __tablename__ = 'item_location'
    
    inventory_id = db.Column(db.Integer, primary_key=True, nullable=False)
    item_id = db.Column(db.Integer, primary_key=True, nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey('location.location_id'), primary_key=True, nullable=False)
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False)
    
    __table_args__ = (
        db.ForeignKeyConstraint(['item_id', 'inventory_id'], ['inventory.item_id', 'inventory.inventory_id']),
    )
    
    location = db.relationship('Location', backref='item_locations')

class DonationIntake(db.Model):
    """Donation intake - receiving donations into warehouse inventory (AIDMGMT)"""
    __tablename__ = 'dnintake'
    
    donation_id = db.Column(db.Integer, db.ForeignKey('donation.donation_id'), primary_key=True)
    inventory_id = db.Column(db.Integer, db.ForeignKey('inventory.inventory_id'), primary_key=True)
    intake_date = db.Column(db.Date, nullable=False)
    comments_text = db.Column(db.String(255))
    status_code = db.Column(db.CHAR(1), nullable=False)
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False)
    update_by_id = db.Column(db.String(20), nullable=False)
    update_dtime = db.Column(db.DateTime)
    verify_by_id = db.Column(db.String(20), nullable=False)
    verify_dtime = db.Column(db.DateTime)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)
    
    donation = db.relationship('Donation', backref='intakes')
    inventory = db.relationship('Inventory', backref='donation_intakes')
    warehouse = db.relationship('Warehouse', 
                                primaryjoin='foreign(DonationIntake.inventory_id)==Warehouse.warehouse_id',
                                viewonly=True,
                                uselist=False)

class DonationIntakeItem(db.Model):
    """Donation Intake Item - Batch-level intake tracking for donations
    
    Tracks each batch of items received in a donation with batch numbers,
    dates, expiry, and quantities. If batch doesn't exist in itembatch table,
    create it with batch_id and zero quantities, then update with intake amounts.
    
    IMPORTANT: batch_no is required and part of composite PK. If no manufacturer batch
    number exists, use the item code as the batch_no value.
    
    Status Codes:
        P = Pending verification
        V = Verified
    """
    __tablename__ = 'dnintake_item'
    
    donation_id = db.Column(db.Integer, primary_key=True)
    inventory_id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, primary_key=True)
    batch_no = db.Column(db.String(20), primary_key=True)
    batch_date = db.Column(db.Date, nullable=False)
    expiry_date = db.Column(db.Date, nullable=False)
    uom_code = db.Column(db.String(25), db.ForeignKey('unitofmeasure.uom_code'), nullable=False)
    avg_unit_value = db.Column(db.Numeric(10, 2), nullable=False)
    ext_item_cost = db.Column(db.Numeric(12, 2), nullable=False, default=0.00)
    usable_qty = db.Column(db.Numeric(12, 2), nullable=False, default=0.00)
    defective_qty = db.Column(db.Numeric(12, 2), nullable=False, default=0.00)
    expired_qty = db.Column(db.Numeric(12, 2), nullable=False, default=0.00)
    status_code = db.Column(db.CHAR(1), nullable=False, default='P')
    comments_text = db.Column(db.String(255))
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False)
    update_by_id = db.Column(db.String(20), nullable=False)
    update_dtime = db.Column(db.DateTime, nullable=False)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)
    
    __table_args__ = (
        db.ForeignKeyConstraint(['donation_id', 'inventory_id'], ['dnintake.donation_id', 'dnintake.inventory_id'], name='fk_dnintake_item_intake'),
        db.ForeignKeyConstraint(['donation_id', 'item_id'], ['donation_item.donation_id', 'donation_item.item_id'], name='fk_dnintake_item_donation_item'),
        db.CheckConstraint("batch_no = UPPER(batch_no)", name='c_dnintake_item_1a'),
        db.CheckConstraint("batch_date <= CURRENT_DATE", name='c_dnintake_item_1b'),
        db.CheckConstraint("expiry_date >= batch_date", name='c_dnintake_item_1c'),
        db.CheckConstraint("avg_unit_value > 0.00", name='c_dnintake_item_1d'),
        db.CheckConstraint("ext_item_cost >= 0.00", name='c_dnintake_item_1e'),
        db.CheckConstraint("usable_qty >= 0.00", name='c_dnintake_item_2'),
        db.CheckConstraint("defective_qty >= 0.00", name='c_dnintake_item_3'),
        db.CheckConstraint("expired_qty >= 0.00", name='c_dnintake_item_4'),
        db.CheckConstraint("status_code IN ('P', 'V')", name='c_dnintake_item_5'),
        db.Index('dk_dnintake_item_1', 'inventory_id', 'item_id'),
        db.Index('dk_dnintake_item_2', 'item_id'),
        db.PrimaryKeyConstraint('donation_id', 'inventory_id', 'item_id', 'batch_no', name='pk_dnintake_item'),
    )
    
    intake = db.relationship('DonationIntake', backref='items')
    item = db.relationship('Item',
                          primaryjoin='DonationIntakeItem.item_id==Item.item_id',
                          foreign_keys=[item_id],
                          backref='donation_intake_items')
    uom = db.relationship('UnitOfMeasure', backref='donation_intake_items')
    
    __mapper_args__ = {
        'version_id_col': version_nbr
    }

# COMMENTED OUT: These tables (xfintake, xfintake_item) don't exist in the database
# Uncomment when the transfer intake feature is implemented
# class TransferIntake(db.Model):
#     """Transfer intake - receiving transfers at destination warehouse (AIDMGMT)"""
#     __tablename__ = 'xfintake'
#     
#     transfer_id = db.Column(db.Integer, db.ForeignKey('transfer.transfer_id'), primary_key=True)
#     inventory_id = db.Column(db.Integer, db.ForeignKey('warehouse.warehouse_id'), primary_key=True)
#     intake_date = db.Column(db.Date, nullable=False)
#     comments_text = db.Column(db.String(255))
#     status_code = db.Column(db.CHAR(1), nullable=False)
#     create_by_id = db.Column(db.String(20), nullable=False)
#     create_dtime = db.Column(db.DateTime, nullable=False)
#     update_by_id = db.Column(db.String(20), nullable=False)
#     update_dtime = db.Column(db.DateTime)
#     verify_by_id = db.Column(db.String(20), nullable=False)
#     verify_dtime = db.Column(db.DateTime)
#     version_nbr = db.Column(db.Integer, nullable=False, default=1)
#     
#     transfer = db.relationship('Transfer', backref='intakes')
#     warehouse = db.relationship('Warehouse', foreign_keys=[inventory_id], backref='transfer_intakes')
# 
# class TransferIntakeItem(db.Model):
#     """Items in transfer intake (AIDMGMT)"""
#     __tablename__ = 'xfintake_item'
#     
#     transfer_id = db.Column(db.Integer, primary_key=True)
#     inventory_id = db.Column(db.Integer, primary_key=True)
#     item_id = db.Column(db.Integer, db.ForeignKey('item.item_id'), primary_key=True)
#     usable_qty = db.Column(db.DECIMAL(12, 2), nullable=False)
#     location1_id = db.Column(db.Integer, db.ForeignKey('location.location_id'))
#     defective_qty = db.Column(db.DECIMAL(12, 2), nullable=False)
#     location2_id = db.Column(db.Integer, db.ForeignKey('location.location_id'))
#     expired_qty = db.Column(db.DECIMAL(12, 2), nullable=False)
#     location3_id = db.Column(db.Integer, db.ForeignKey('location.location_id'))
#     uom_code = db.Column(db.String(25), db.ForeignKey('unitofmeasure.uom_code'), nullable=False)
#     status_code = db.Column(db.CHAR(1), nullable=False)
#     comments_text = db.Column(db.String(255))
#     create_by_id = db.Column(db.String(20), nullable=False)
#     create_dtime = db.Column(db.DateTime, nullable=False)
#     update_by_id = db.Column(db.String(20), nullable=False)
#     update_dtime = db.Column(db.DateTime, nullable=False)
#     version_nbr = db.Column(db.Integer, nullable=False, default=1)
#     
#     __table_args__ = (
#         db.ForeignKeyConstraint(['transfer_id', 'inventory_id'], ['xfintake.transfer_id', 'xfintake.inventory_id']),
#     )
#     
#     item = db.relationship('Item',
#                           primaryjoin='TransferIntakeItem.item_id==Item.item_id',
#                           foreign_keys=[item_id],
#                           backref='transfer_intake_items')
#     unit_of_measure = db.relationship('UnitOfMeasure')

class TransferReturn(db.Model):
    """Transfer returns - items being returned from destination to source warehouse (AIDMGMT)"""
    __tablename__ = 'xfreturn'
    
    xfreturn_id = db.Column(db.Integer, primary_key=True)
    fr_inventory_id = db.Column(db.Integer, db.ForeignKey('warehouse.warehouse_id'), nullable=False)
    to_inventory_id = db.Column(db.Integer, db.ForeignKey('warehouse.warehouse_id'), nullable=False)
    return_date = db.Column(db.Date, nullable=False)
    reason_text = db.Column(db.String(255))
    status_code = db.Column(db.CHAR(1), nullable=False)
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False)
    update_by_id = db.Column(db.String(20), nullable=False)
    update_dtime = db.Column(db.DateTime)
    verify_by_id = db.Column(db.String(20), nullable=False)
    verify_dtime = db.Column(db.DateTime)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)
    
    from_warehouse = db.relationship('Warehouse', foreign_keys=[fr_inventory_id], backref='returns_sent')
    to_warehouse = db.relationship('Warehouse', foreign_keys=[to_inventory_id], backref='returns_received')

class TransferReturnItem(db.Model):
    """Items in transfer return (AIDMGMT)"""
    __tablename__ = 'xfreturn_item'
    
    xfreturn_id = db.Column(db.Integer, db.ForeignKey('xfreturn.xfreturn_id'), primary_key=True)
    inventory_id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('item.item_id'), primary_key=True)
    usable_qty = db.Column(db.DECIMAL(12, 2), nullable=False)
    defective_qty = db.Column(db.DECIMAL(12, 2), nullable=False)
    expired_qty = db.Column(db.DECIMAL(12, 2), nullable=False)
    uom_code = db.Column(db.String(25), db.ForeignKey('unitofmeasure.uom_code'), nullable=False)
    reason_text = db.Column(db.String(255))
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False)
    update_by_id = db.Column(db.String(20), nullable=False)
    update_dtime = db.Column(db.DateTime, nullable=False)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)
    
    __table_args__ = (
        db.ForeignKeyConstraint(['item_id', 'inventory_id'], ['inventory.item_id', 'inventory.inventory_id']),
    )
    
    transfer_return = db.relationship('TransferReturn', backref='items')
    item = db.relationship('Item', backref='transfer_return_items')
    unit_of_measure = db.relationship('UnitOfMeasure')

class ReturnIntake(db.Model):
    """Return intake - receiving returned items at source warehouse (AIDMGMT)"""
    __tablename__ = 'rtintake'
    
    xfreturn_id = db.Column(db.Integer, db.ForeignKey('xfreturn.xfreturn_id'), primary_key=True)
    inventory_id = db.Column(db.Integer, db.ForeignKey('inventory.inventory_id'), primary_key=True)
    intake_date = db.Column(db.Date, nullable=False)
    comments_text = db.Column(db.String(255))
    status_code = db.Column(db.CHAR(1), nullable=False)
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False)
    update_by_id = db.Column(db.String(20), nullable=False)
    update_dtime = db.Column(db.DateTime)
    verify_by_id = db.Column(db.String(20), nullable=False)
    verify_dtime = db.Column(db.DateTime)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)
    
    transfer_return = db.relationship('TransferReturn', backref='intakes')
    inventory = db.relationship('Inventory', backref='return_intakes')

class ReturnIntakeItem(db.Model):
    """Items in return intake (AIDMGMT)"""
    __tablename__ = 'rtintake_item'
    
    xfreturn_id = db.Column(db.Integer, primary_key=True)
    inventory_id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('item.item_id'), primary_key=True)
    usable_qty = db.Column(db.DECIMAL(12, 2), nullable=False)
    location1_id = db.Column(db.Integer, db.ForeignKey('location.location_id'))
    defective_qty = db.Column(db.DECIMAL(12, 2), nullable=False)
    location2_id = db.Column(db.Integer, db.ForeignKey('location.location_id'))
    expired_qty = db.Column(db.DECIMAL(12, 2), nullable=False)
    location3_id = db.Column(db.Integer, db.ForeignKey('location.location_id'))
    uom_code = db.Column(db.String(25), db.ForeignKey('unitofmeasure.uom_code'), nullable=False)
    status_code = db.Column(db.CHAR(1), nullable=False)
    comments_text = db.Column(db.String(255))
    create_by_id = db.Column(db.String(20), nullable=False)
    create_dtime = db.Column(db.DateTime, nullable=False)
    update_by_id = db.Column(db.String(20), nullable=False)
    update_dtime = db.Column(db.DateTime, nullable=False)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)
    
    __table_args__ = (
        db.ForeignKeyConstraint(['xfreturn_id', 'inventory_id'], ['rtintake.xfreturn_id', 'rtintake.inventory_id']),
    )
    
    item = db.relationship('Item',
                          primaryjoin='ReturnIntakeItem.item_id==Item.item_id',
                          foreign_keys=[item_id],
                          backref='return_intake_items')
    unit_of_measure = db.relationship('UnitOfMeasure')

class AgencyAccountRequest(db.Model):
    """Agency account creation request with workflow (S=submitted, R=review, A=approved, D=denied)"""
    __tablename__ = 'agency_account_request'
    
    request_id = db.Column(db.Integer, primary_key=True)
    
    agency_name = db.Column(db.String(120), nullable=False)
    contact_name = db.Column(db.String(80), nullable=False)
    contact_phone = db.Column(db.String(20), nullable=False)
    contact_email = db.Column(db.String(200), nullable=False)
    reason_text = db.Column(db.String(255), nullable=False)
    
    agency_id = db.Column(db.Integer, db.ForeignKey('agency.agency_id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.user_id'))
    
    status_code = db.Column(db.CHAR(1), nullable=False)
    status_reason = db.Column(db.String(255))
    
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.user_id'), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=jamaica_now)
    updated_by_id = db.Column(db.Integer, db.ForeignKey('user.user_id'), nullable=False)
    updated_at = db.Column(db.DateTime, nullable=False, default=jamaica_now)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)
    
    agency = db.relationship('Agency', foreign_keys=[agency_id], backref='account_requests')
    user = db.relationship('User', foreign_keys=[user_id], backref='account_requests')
    created_by = db.relationship('User', foreign_keys=[created_by_id], backref='requests_created')
    updated_by = db.relationship('User', foreign_keys=[updated_by_id], backref='requests_updated')

class AgencyAccountRequestAudit(db.Model):
    """Immutable audit log for agency account request workflow events"""
    __tablename__ = 'agency_account_request_audit'
    
    audit_id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey('agency_account_request.request_id'), nullable=False)
    event_type = db.Column(db.String(24), nullable=False)
    event_notes = db.Column(db.String(255))
    actor_user_id = db.Column(db.Integer, db.ForeignKey('user.user_id'), nullable=False)
    event_dtime = db.Column(db.DateTime, nullable=False, default=jamaica_now)
    version_nbr = db.Column(db.Integer, nullable=False, default=1)
    
    request = db.relationship('AgencyAccountRequest', backref='audit_log')
    actor = db.relationship('User', foreign_keys=[actor_user_id], backref='audit_actions')

class Notification(db.Model):
    """In-app notifications for users"""
    __tablename__ = 'notification'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.user_id'), nullable=False)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouse.warehouse_id'))
    reliefrqst_id = db.Column(db.Integer, db.ForeignKey('reliefrqst.reliefrqst_id'))
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='unread')
    link_url = db.Column(db.String(500))
    payload = db.Column(db.Text)
    is_archived = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=jamaica_now)
    
    user = db.relationship('User', backref='notifications')
    warehouse = db.relationship('Warehouse', backref='notifications')
    relief_request = db.relationship('ReliefRqst', backref='notifications')
