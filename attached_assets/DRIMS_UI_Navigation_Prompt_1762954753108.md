# DRIMS Application Rebuild Prompt
## Disaster Relief Inventory Management System - UI & Navigation Specification

---

## 🎯 Objective
Rebuild the DRIMS (Disaster Relief Inventory Management System) Flask application with the **exact same UI design, navigation structure, and user experience** as the reference application. The database schema MUST remain unchanged - only UI and navigation implementation required.

---

## 📋 Critical Requirements

### ✅ MUST PRESERVE (Do Not Change)
1. **Database Schema** - Use the exact PostgreSQL schema provided (23 tables)
2. **Data Models** - All SQLAlchemy models must match the schema exactly
3. **Business Logic** - Core workflow and validation rules
4. **User Roles & Permissions** - Role-based access control logic

### ✅ MUST REPLICATE (Exact Match Required)
1. **UI Design & Styling** - Jamaica Government colors and branding
2. **Navigation Structure** - Sidebar, header, and menu organization
3. **Page Layouts** - Dashboard cards, tables, forms, and components
4. **User Experience Flow** - Multi-step workflows and interactions

---

## 🎨 UI Design System

### Color Palette (Government of Jamaica Branding)
```css
--goj-green: #009639        /* Primary brand color */
--goj-gold: #FDB913         /* Secondary accent */
--goj-black: #000000        /* Text and borders */
--goj-light-green: #E8F5E9  /* Backgrounds and highlights */
```

### Layout Structure
- **Fixed Top Header**: 60px height, gradient green background
- **Fixed Left Sidebar**: 260px width (collapsible to 70px)
- **Main Content Area**: Responsive with 30px padding
- **Card-Based UI**: Rounded corners (12px), subtle shadows

### Typography
- **Font Family**: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif
- **Background**: #f5f7fa (light gray)
- **Headers**: Bold, with icon prefixes
- **Body**: 0.9rem, regular weight

---

## 🧭 Navigation Architecture

### Top Header Components
```
┌─────────────────────────────────────────────────────────────┐
│ [☰] DRIMS Logo  |                      | 🔔 [Profile ▾]  │
└─────────────────────────────────────────────────────────────┘
```

**Elements:**
1. **Hamburger Menu** - Toggle sidebar collapse
2. **Logo & Brand** - "DRIMS" with Jamaica coat of arms
3. **Notification Bell** - Real-time notification badge (red dot for unread)
4. **User Profile Dropdown** - Name, role, logout option

### Left Sidebar Menu Structure

**Collapsible sidebar with role-based navigation items:**

```
┌──────────────────────────────┐
│  NAVIGATION SECTIONS         │
│                              │
│  🏠 Dashboard                │
│                              │
│  📊 LOGISTICS (Admin only)   │
│    └─ Hubs & Locations       │
│    └─ Stock by Location      │
│    └─ All Needs Lists        │
│                              │
│  📦 INVENTORY                │
│    └─ Items Catalog          │
│    └─ Receive Stock          │
│    └─ Distribute Stock       │
│                              │
│  📋 NEEDS LISTS              │
│    └─ My Needs Lists         │
│    └─ Create New Request     │
│                              │
│  👥 ADMIN (Admin only)       │
│    └─ Users                  │
│    └─ Roles                  │
│    └─ Disaster Events        │
│                              │
│  ⚙️  SETTINGS                │
│    └─ Profile                │
│    └─ Preferences            │
│                              │
└──────────────────────────────┘
```

**Navigation Behavior:**
- Active page: Green background (#E8F5E9) with 4px left border
- Hover effect: Light green background
- Icons: Bootstrap Icons (bi-) font library
- Section headers: Uppercase, gray, 0.75rem font
- Collapsed mode: Only icons visible, tooltips on hover

---

## 📱 Dashboard Layouts (Role-Based)

### Common Dashboard Components

#### KPI Cards (Compact Design)
```html
<div class="card border-0 shadow-sm h-100 kpi-card">
  <div class="card-body p-3">
    <div class="d-flex align-items-center">
      <div class="me-3 text-primary">
        <i class="bi bi-[icon] fs-3"></i>
      </div>
      <div>
        <div class="text-muted small">[Label]</div>
        <div class="h4 mb-0 fw-bold">[Value]</div>
      </div>
    </div>
  </div>
</div>
```

**KPI Card Features:**
- Hover animation: translateY(-2px)
- Icon colors: primary, info, success, warning, danger
- Large bold numbers with context labels
- Optional secondary values (e.g., "5/10" active/total)

### Role-Specific Dashboards

#### 1. Logistics Manager Dashboard
**Sections:**
- **KPI Row (5 cards)**: Main Hubs, Sub-Hubs, Agency Hubs, Gov Stock, Open Requests
- **Hub Status Overview**: Active/Inactive breakdown by hub type
- **Category Distribution Chart**: Horizontal bar chart using Chart.js
- **Hub Status Table**: Clickable rows to view inventory
- **Approval Queues (3 columns)**: Submitted, Fulfilment Prepared, Awaiting Approval

#### 2. Main Hub Dashboard
**Sections:**
- **KPI Row**: Hub Info, Stock Count, Recent Transactions, Pending Transfers
- **Stock Alerts**: Low stock warnings
- **Recent Activity**: Transaction history
- **Quick Actions**: Receive, Distribute, Transfer

#### 3. Sub-Hub Dashboard
**Sections:**
- **KPI Row**: Hub Info, Stock Count, Allocated Items, Dispatch Queue
- **My Needs Lists**: Active requests
- **Dispatch Ready**: Items ready to send
- **Received Shipments**: Incoming deliveries

#### 4. Agency Hub Dashboard
**Sections:**
- **KPI Row**: Hub Info, Active Requests, Completed Requests, Items Received
- **My Needs Lists**: Draft, submitted, approved, dispatched, received
- **Create New Request**: Quick action button
- **Notifications**: Hub-specific alerts

#### 5. System Administrator Dashboard
**Sections:**
- **System Health**: Database stats, user activity, error logs
- **User Management**: Recent signups, role assignments
- **Configuration**: Feature flags, settings
- **Audit Logs**: System activity tracking

---

## 📋 Page Templates & Components

### Needs List Detail Page

**Layout Structure:**
```
┌───────────────────────────────────────────────────────────┐
│  ◀ Back to Lists        [Status Badge]      [Actions ▾]   │
├───────────────────────────────────────────────────────────┤
│  Needs List #NL-000001                                    │
│  Agency: Kingston Central | Priority: High                │
├───────────────────────────────────────────────────────────┤
│  📋 Request Information                                    │
│  ┌─────────────────────────────────────────────────────┐ │
│  │ Created: 2025-01-15 | Submitted: 2025-01-15         │ │
│  │ Items: 5 | Total Units: 250                          │ │
│  └─────────────────────────────────────────────────────┘ │
├───────────────────────────────────────────────────────────┤
│  📦 Requested Items                                        │
│  ┌─────────────────────────────────────────────────────┐ │
│  │ Item | SKU | Requested | Allocated | Status         │ │
│  ├─────────────────────────────────────────────────────┤ │
│  │ Water Bottles | H2O-500 | 100 | 100 | ✓ Fulfilled  │ │
│  │ Rice (5kg) | RICE-5KG | 50 | 50 | ✓ Fulfilled      │ │
│  └─────────────────────────────────────────────────────┘ │
├───────────────────────────────────────────────────────────┤
│  🚚 Fulfilment Details (if prepared)                       │
│  ┌─────────────────────────────────────────────────────┐ │
│  │ Source Hub | Item | Quantity                         │ │
│  ├─────────────────────────────────────────────────────┤ │
│  │ Spanish Town Main | Water Bottles | 100 from Main   │ │
│  └─────────────────────────────────────────────────────┘ │
├───────────────────────────────────────────────────────────┤
│  📝 Timeline & Activity Log                                │
│  ┌─────────────────────────────────────────────────────┐ │
│  │ 🟢 Created - Jan 15, 2025 10:00 AM by John Doe      │ │
│  │ 🟢 Submitted - Jan 15, 2025 10:30 AM                │ │
│  │ 🟢 Prepared - Jan 15, 2025 11:00 AM by Jane Smith   │ │
│  │ 🟢 Approved - Jan 15, 2025 11:30 AM by Admin        │ │
│  └─────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────┘
```

**Status Badge Colors:**
- Draft: `badge-secondary`
- Submitted: `badge-primary`
- Fulfilment Prepared: `badge-info`
- Awaiting Approval: `badge-warning`
- Approved: `badge-success`
- Dispatched: `badge-success` with truck icon
- Received: `badge-dark`
- Completed: `badge-success` with checkmark

### Form Styling

**Input Fields:**
```html
<div class="mb-3">
  <label class="form-label fw-semibold">Field Label</label>
  <input type="text" class="form-control" placeholder="Enter value...">
</div>
```

**Select Dropdowns:**
```html
<select class="form-select">
  <option value="">-- Select Option --</option>
  <option value="1">Option 1</option>
</select>
```

**Action Buttons:**
- Primary: `btn btn-primary` (green background)
- Secondary: `btn btn-outline-primary` (green border, white background)
- Danger: `btn btn-danger` (red background)
- Cancel/Back: `btn btn-secondary` (gray)

### Tables

**Standard Table Layout:**
```html
<div class="table-responsive">
  <table class="table table-hover table-sm mb-0">
    <thead class="bg-light">
      <tr>
        <th class="py-2 px-3">Column 1</th>
        <th class="py-2 px-3">Column 2</th>
        <th class="py-2 px-3 text-end">Actions</th>
      </tr>
    </thead>
    <tbody>
      <!-- Rows with hover effect -->
    </tbody>
  </table>
</div>
```

**Features:**
- Hover effect: Light background change
- Clickable rows: `cursor: pointer`
- Badges for status indicators
- Icons for actions (edit, delete, view)
- Responsive scrolling on small screens

---

## 🔔 Notification System

### Notification Bell (Top Header)
```html
<div class="position-relative">
  <button class="btn btn-link text-white position-relative">
    <i class="bi bi-bell fs-5"></i>
    <span class="position-absolute top-0 start-100 translate-middle badge rounded-pill bg-danger">
      [count]
    </span>
  </button>
</div>
```

### Notification Offcanvas Panel
**Slide-in from right side when bell is clicked:**

```
┌─────────────────────────────┐
│  Notifications  [Mark All]  │
├─────────────────────────────┤
│  📋 New Request             │
│  NL-000045 submitted        │
│  2 hours ago      [New]     │
├─────────────────────────────┤
│  ✓ Approved                 │
│  NL-000044 approved         │
│  5 hours ago                │
├─────────────────────────────┤
│  🚚 Dispatched              │
│  NL-000043 shipped          │
│  1 day ago                  │
└─────────────────────────────┘
```

**Notification Types with Icons:**
- `needs_list_submitted`: 📋 (bi-inbox)
- `needs_list_prepared`: 📦 (bi-box-seam)
- `needs_list_approved`: ✓ (bi-check-circle)
- `needs_list_dispatched`: 🚚 (bi-truck)
- `needs_list_received`: 📥 (bi-download)
- `fulfilment_change_requested`: 🔄 (bi-arrow-repeat)
- `fulfilment_change_approved`: ✓✓ (bi-check2-circle)

**Behavior:**
- Real-time polling every 30 seconds
- Unread: Bold text with "New" badge
- Click notification: Navigate to related page and mark as read
- "Mark All Read" button at top

---

## 🚀 Multi-Step Workflows

### Create Needs List Flow
1. **Step 1 - Basic Info**: Agency hub, disaster event, priority, notes
2. **Step 2 - Add Items**: Search items, add to list with quantities and justification
3. **Step 3 - Review**: Summary table, edit quantities, remove items
4. **Step 4 - Submit/Save**: Submit for approval or save as draft

### Prepare Fulfilment Flow
1. **View Request**: Display needs list items
2. **Allocate Stock**: Select source hubs for each item
3. **Validate Availability**: Check stock levels in real-time
4. **Lock for Editing**: Prevent concurrent modifications
5. **Submit Preparation**: Move to "Fulfilment Prepared" status

### Dispatch & Receipt Flow
1. **Dispatch**: Warehouse supervisor marks as dispatched with notes
2. **In Transit**: Status updates to "Dispatched"
3. **Receipt**: Agency hub confirms receipt with signature/notes
4. **Completion**: Status updates to "Completed"

---

## 🔐 Role-Based Access Control

### User Roles & Permissions
| Role | Dashboard | Create Needs List | Prepare Fulfilment | Approve | Dispatch | Receive | Manage Users |
|------|-----------|-------------------|--------------------|---------|-----------|---------|--------------
| System Administrator | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Logistics Manager | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ |
| Logistics Officer | ✓ | ✗ | ✓ | ✓ | ✗ | ✗ | ✗ |
| Main Hub (Warehouse Supervisor) | ✓ | ✗ | ✓ | ✗ | ✓ | ✓ | ✗ |
| Sub-Hub (Warehouse Supervisor) | ✓ | ✗ | ✗ | ✗ | ✓ | ✓ | ✗ |
| Agency Hub | ✓ | ✓ | ✗ | ✗ | ✗ | ✓ | ✗ |
| Inventory Clerk | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Auditor | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |

**Permission Checks:**
- Use `@role_required` decorator for route protection
- Hide/show UI elements based on `current_user.role`
- Return 403 Forbidden for unauthorized access

---

## 📊 Charts & Visualizations

### Chart.js Integration
**Required charts:**
1. **Category Distribution** - Horizontal bar chart
2. **Stock Trends** - Line chart (optional, future enhancement)
3. **Hub Activity** - Donut/pie chart (optional)

**Chart Configuration:**
```javascript
new Chart(ctx, {
  type: 'bar',
  data: {
    labels: [...],
    datasets: [{
      label: 'Units',
      data: [...],
      backgroundColor: 'rgba(13, 110, 253, 0.7)',
      borderColor: 'rgb(13, 110, 253)',
      borderWidth: 1
    }]
  },
  options: {
    indexAxis: 'y',  // Horizontal bars
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false }
    }
  }
});
```

---

## 🗄️ Database Schema (MUST NOT CHANGE)

### Key Tables (23 Total)
1. **user** - User accounts and authentication
2. **role** - User roles (RBAC)
3. **location** - Hubs (Main, Sub, Agency)
4. **item** - Inventory items catalog
5. **transaction** - Stock movements (intake/distribute)
6. **needs_list** - Request from agencies
7. **needs_list_item** - Items in a needs list
8. **needs_list_fulfilment** - Allocation from source hubs
9. **needs_list_fulfilment_version** - Change history
10. **fulfilment_change_request** - Request to modify fulfilment
11. **fulfilment_edit_log** - Audit trail
12. **notification** - In-app notifications
13. **disaster_event** - Emergency events
14. **donor** - Donation sources
15. **beneficiary** - Recipients
16. **distribution_package** - Alternative distribution method
17. **package_item** - Items in package
18. **package_status_history** - Package audit trail
19. **transfer_request** - Inter-hub transfers
20. **user_hub** - User-hub assignments
21. **user_role** - User-role assignments
22. **offline_sync_log** - Offline mode sync tracking
23. **package_item_allocation** - Package allocation by depot

**Schema File:** `SCHEMA.sql` (495 lines)
- All foreign keys defined
- Indexes for performance
- Timestamps for audit trails

---

## 🛠️ Technology Stack

### Backend
- **Framework**: Flask 3.x
- **Database**: PostgreSQL (via SQLAlchemy ORM)
- **Authentication**: Flask-Login
- **Forms**: Flask-WTF
- **Migrations**: Flask-Migrate (Alembic)

### Frontend
- **CSS Framework**: Bootstrap 5.3.3
- **Icons**: Bootstrap Icons 1.11.3
- **Charts**: Chart.js (latest stable)
- **JavaScript**: Vanilla JS (no framework required)

### Dependencies (requirements.txt)
```
Flask>=3.0.0
Flask-SQLAlchemy>=3.1.1
Flask-Login>=0.6.3
Flask-WTF>=1.2.1
Flask-Migrate>=4.0.5
psycopg2-binary>=2.9.9
python-dotenv>=1.0.0
Werkzeug>=3.0.1
```

---

## 📂 Project Structure

```
drims/
├── app.py                    # Main Flask application
├── models.py                 # SQLAlchemy models (MUST match schema)
├── forms.py                  # WTForms for input validation
├── routes/                   # Route blueprints
│   ├── auth.py               # Login/logout
│   ├── dashboard.py          # Role-based dashboards
│   ├── inventory.py          # Stock management
│   ├── needs_lists.py        # Needs list workflows
│   ├── admin.py              # User/role management
│   └── notifications.py      # Notification endpoints
├── templates/                # Jinja2 templates
│   ├── base.html             # Base layout (header, sidebar, scripts)
│   ├── dashboard_*.html      # Role-specific dashboards
│   ├── needs_list_*.html     # Needs list pages
│   ├── inventory_*.html      # Inventory pages
│   └── admin_*.html          # Admin pages
├── static/                   # Static assets
│   ├── css/                  # Custom stylesheets (if needed)
│   ├── js/                   # JavaScript files
│   │   ├── offline.js        # Offline mode (optional)
│   │   └── notifications.js  # Notification handling
│   └── images/               # Logos and icons
├── migrations/               # Database migrations
├── config.py                 # Configuration settings
├── requirements.txt          # Python dependencies
└── README.md                 # Documentation
```

---

## 🎯 Implementation Checklist

### Phase 1: Foundation
- [ ] Set up Flask project structure
- [ ] Configure database connection (PostgreSQL)
- [ ] Implement all 23 SQLAlchemy models from schema
- [ ] Create base.html template with header, sidebar, notification system
- [ ] Set up Flask-Login authentication

### Phase 2: Core UI Components
- [ ] Implement collapsible sidebar with role-based navigation
- [ ] Create notification bell with offcanvas panel
- [ ] Build reusable KPI card component
- [ ] Design table layouts with hover effects
- [ ] Implement form styling (inputs, selects, buttons)

### Phase 3: Dashboards
- [ ] Logistics Manager dashboard (5 KPIs, charts, approval queues)
- [ ] Main Hub dashboard
- [ ] Sub-Hub dashboard
- [ ] Agency Hub dashboard
- [ ] System Administrator dashboard
- [ ] Inventory Clerk dashboard
- [ ] Auditor dashboard

### Phase 4: Workflows
- [ ] Create Needs List (multi-step form)
- [ ] Prepare Fulfilment (stock allocation)
- [ ] Approve/Reject (Logistics Manager)
- [ ] Dispatch (Warehouse Supervisor)
- [ ] Receive & Complete (Agency Hub)
- [ ] Request Fulfilment Change (change request flow)

### Phase 5: Inventory & Admin
- [ ] Items catalog (CRUD)
- [ ] Receive stock (intake transactions)
- [ ] Distribute stock
- [ ] Transfer requests
- [ ] User management (CRUD, role assignments)
- [ ] Disaster events management

### Phase 6: Notifications & Polish
- [ ] Real-time notification polling
- [ ] Notification creation triggers
- [ ] Mark as read/unread
- [ ] Sidebar active state detection
- [ ] Responsive design testing
- [ ] Cross-browser compatibility

### Phase 7: Testing & Deployment
- [ ] Unit tests for models
- [ ] Integration tests for workflows
- [ ] Manual UI testing on all roles
- [ ] Database migration testing
- [ ] Production deployment guide

---

## 🚨 Critical Implementation Notes

### 1. Database Schema Integrity
**DO NOT MODIFY:**
- Table names, column names, or data types
- Foreign key relationships
- Primary key definitions
- Index configurations

**Allowed:**
- Adding new indexes for query optimization (document reasons)
- Creating database views for reporting (non-destructive)

### 2. Sidebar Navigation State
**Active page detection:**
```python
# In route handlers
@bp.route('/dashboard')
def dashboard():
    return render_template('dashboard.html', active_page='dashboard')
```

```html
<!-- In base.html -->
<a href="{{ url_for('dashboard') }}" 
   class="nav-item-link {% if active_page == 'dashboard' %}active{% endif %}">
  <i class="bi bi-house-door"></i>
  <span class="nav-label">Dashboard</span>
</a>
```

### 3. Notification Polling
**JavaScript implementation:**
```javascript
async function fetchUnreadCount() {
  const response = await fetch('/notifications/unread-count');
  const data = await response.json();
  updateBadge(data.count);
}

setInterval(fetchUnreadCount, 30000); // Every 30 seconds
```

### 4. Chart.js Integration
**Include in base.html:**
```html
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
```

**Initialize in page template:**
```javascript
const ctx = document.getElementById('categoryChart');
new Chart(ctx, { /* config */ });
```

### 5. Role-Based UI Rendering
**Jinja2 template logic:**
```html
{% if current_user.role in ['System Administrator', 'Logistics Manager'] %}
  <a href="{{ url_for('admin.users') }}" class="nav-item-link">
    <i class="bi bi-people"></i>
    <span class="nav-label">Users</span>
  </a>
{% endif %}
```

---

## 🎨 Design Assets

### Jamaica Coat of Arms
- **File**: `static/images/jamaica_coat_of_arms.png`
- **Usage**: Header logo (35px height)
- **Alternative**: Use text "DRIMS" if image unavailable

### Bootstrap Icons
- **CDN**: `https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css`
- **Usage**: Prefix all icons with `bi-` (e.g., `bi-house-door`, `bi-bell`)

### Custom CSS (Minimal)
Most styling uses Bootstrap 5 utilities. Custom CSS only for:
- Sidebar transitions and collapse animations
- KPI card hover effects
- Notification badge positioning
- Chart container sizing

---

## 📝 Sample Code Snippets

### Role-Required Decorator
```python
from functools import wraps
from flask import abort
from flask_login import current_user

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if current_user.role not in roles:
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@bp.route('/admin/users')
@login_required
@role_required('System Administrator')
def manage_users():
    # Admin-only page
    pass
```

### Notification Creation
```python
def create_notification(user_id, title, message, notification_type, link_url=None):
    notification = Notification(
        user_id=user_id,
        title=title,
        message=message,
        type=notification_type,
        status='unread',
        link_url=link_url,
        is_archived=False,
        created_at=datetime.utcnow()
    )
    db.session.add(notification)
    db.session.commit()
```

### Stock Availability Check
```python
def check_stock_availability(location_id, item_sku, required_qty):
    """Check if sufficient stock exists at a location."""
    intake = db.session.query(func.sum(Transaction.qty)).filter(
        Transaction.location_id == location_id,
        Transaction.item_sku == item_sku,
        Transaction.ttype == 'INTAKE'
    ).scalar() or 0
    
    outflow = db.session.query(func.sum(Transaction.qty)).filter(
        Transaction.location_id == location_id,
        Transaction.item_sku == item_sku,
        Transaction.ttype == 'DISTRIB'
    ).scalar() or 0
    
    available = intake - outflow
    return available >= required_qty, available
```

---

## 🔍 Testing Scenarios

### User Role Testing Matrix
Test each workflow with each role to ensure correct permissions:

| Workflow | System Admin | Logistics Manager | Logistics Officer | Warehouse Supervisor | Agency Hub | Inventory Clerk |
|----------|--------------|-------------------|-------------------|----------------------|------------|-----------------|
| Create Needs List | ✓ | ✓ | ✗ | ✗ | ✓ | ✗ |
| Prepare Fulfilment | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ |
| Approve Needs List | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ |
| Dispatch | ✓ | ✓ | ✗ | ✓ | ✗ | ✗ |
| Receive | ✓ | ✓ | ✗ | ✓ | ✓ | ✗ |
| Manage Users | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |

### UI Responsive Testing
- **Desktop**: 1920x1080, 1366x768
- **Tablet**: 768x1024 (iPad)
- **Mobile**: 375x667 (iPhone), 414x896 (iPhone Plus)

### Browser Compatibility
- Chrome (latest)
- Firefox (latest)
- Safari (latest)
- Edge (latest)

---

## 🎓 Development Best Practices

1. **Database Transactions**: Use `db.session.rollback()` on errors
2. **Form Validation**: Validate on both client and server side
3. **Error Handling**: Display user-friendly error messages
4. **Logging**: Log all important actions (create, update, delete)
5. **Security**: Use CSRF tokens, hash passwords, sanitize inputs
6. **Performance**: Eager load relationships, use pagination
7. **Documentation**: Comment complex logic, use docstrings
8. **Code Style**: Follow PEP 8 for Python, use ESLint for JavaScript

---

## 📚 Additional Resources

### Reference Files to Review
1. `base.html` - Complete header, sidebar, and notification system
2. `dashboard_logistics_manager.html` - Full dashboard example
3. `SCHEMA.sql` - Database schema (all 23 tables)
4. `app.py` - Route definitions and business logic (277K file)

### Bootstrap 5 Documentation
- Components: https://getbootstrap.com/docs/5.3/components/
- Utilities: https://getbootstrap.com/docs/5.3/utilities/
- Layout: https://getbootstrap.com/docs/5.3/layout/

### Flask Documentation
- Quickstart: https://flask.palletsprojects.com/quickstart/
- Templates: https://flask.palletsprojects.com/templating/
- SQLAlchemy: https://flask-sqlalchemy.palletsprojects.com/

---

## ✅ Acceptance Criteria

The rebuilt application is considered complete when:

1. ✅ All 23 database tables are created from SCHEMA.sql
2. ✅ UI matches reference application pixel-perfect (colors, fonts, spacing)
3. ✅ Navigation sidebar works identically (collapse, active states, icons)
4. ✅ All 7 role-based dashboards render correctly
5. ✅ Needs List workflow completes end-to-end
6. ✅ Notification system polls and displays correctly
7. ✅ Charts render with correct data
8. ✅ Forms validate and submit properly
9. ✅ Role-based permissions enforce correctly
10. ✅ Application is responsive on mobile/tablet/desktop

---

## 🚀 Getting Started

1. **Clone/Create Project**:
   ```bash
   mkdir drims-rebuild && cd drims-rebuild
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Configure Database**:
   ```bash
   createdb drims
   psql drims < SCHEMA.sql
   ```

3. **Run Application**:
   ```bash
   flask db init  # If using migrations
   flask run
   ```

4. **Create Test Users**:
   ```python
   # In Flask shell
   from app import db
   from models import User
   
   admin = User(
       email='admin@odpem.gov.jm',
       role='System Administrator',
       is_active=True
   )
   admin.set_password('password123')
   db.session.add(admin)
   db.session.commit()
   ```

---

## 📞 Support & Questions

For questions about the database schema or business logic, refer to:
- `DATABASE_SCHEMA.md` (if available in reference files)
- `DEPLOYMENT.md` (if available)
- Comments in `app.py` route handlers

---

**Version:** 1.0  
**Last Updated:** 2025-11-12  
**Author:** DRIMS Rebuild Specification

---

