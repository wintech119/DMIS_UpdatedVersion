# Backend Security Decorators

## Overview
DRIMS includes feature-based route protection decorators that enforce access control at the backend level. These decorators work with the FeatureRegistry to ensure users can only access routes they have permission for.

## Available Decorators

### 1. `@feature_required(feature_key)`
Restricts route access to users who have the specified feature.

**Usage:**
```python
from app.core.decorators import feature_required

@app.route('/inventory')
@login_required
@feature_required('view_inventory')
def list_inventory():
    # Only users with 'view_inventory' feature can access
    return render_template('inventory/list.html')
```

**Features:**
- Redirects unauthenticated users to login
- Shows user-friendly error message with feature name
- Returns 403 Forbidden for unauthorized access

### 2. `@any_feature_required(*feature_keys)`
Allows access if user has ANY of the specified features.

**Usage:**
```python
from app.core.decorators import any_feature_required

@app.route('/dashboard')
@login_required
@any_feature_required('view_dashboard', 'view_reports', 'manage_users')
def dashboard():
    # User needs at least ONE of these features
    return render_template('dashboard.html')
```

**Use Case:** Multi-role pages where different roles can access the same content.

### 3. `@all_features_required(*feature_keys)`
Requires ALL specified features for access.

**Usage:**
```python
from app.core.decorators import all_features_required

@app.route('/reports/export')
@login_required
@all_features_required('view_reports', 'export_data')
def export_report():
    # User must have BOTH features
    return generate_export()
```

**Use Case:** Sensitive operations requiring multiple permissions.

## Implementation Guide

### Step 1: Import Decorators
```python
from flask_login import login_required
from app.core.decorators import feature_required
```

### Step 2: Apply to Routes
Always place decorators in this order:
1. `@app.route()` or `@blueprint.route()`
2. `@login_required`
3. `@feature_required()` or other feature decorators

**Example:**
```python
@items_bp.route('/')
@login_required
@feature_required('view_items')
def list_items():
    items = Item.query.all()
    return render_template('items/list.html', items=items)
```

### Step 3: Handle POST Routes
Apply decorators to both GET and POST handlers:
```python
@items_bp.route('/create', methods=['GET', 'POST'])
@login_required
@feature_required('manage_items')
def create_item():
    if request.method == 'POST':
        # Handle form submission
        pass
    return render_template('items/create.html')
```

## Feature Keys Reference

Common feature keys from FeatureRegistry:
- `view_dashboard` - Access main dashboard
- `view_inventory` - View inventory levels
- `manage_inventory` - Edit inventory records
- `view_items` - View items catalog
- `manage_items` - Create/edit items
- `view_relief_requests` - View relief requests
- `create_relief_requests` - Create new requests
- `approve_relief_requests` - Approve/reject requests
- `prepare_packages` - Package fulfillment
- `approve_packages` - Logistics manager approval
- `manage_users` - User administration
- `manage_agencies` - Agency management
- `view_reports` - Access reports
- `manage_warehouses` - Warehouse management
- `manage_transfers` - Stock transfers

Full list: See `app/core/feature_registry.py` - `FEATURES` dictionary

## Error Handling

### Default Behavior
When a user doesn't have access:
1. **Flash Message:** "You do not have permission to access [feature name]."
2. **Response:** 403 Forbidden error page

### Custom Error Pages
To customize the 403 page, create `templates/errors/403.html`:
```html
{% extends 'base.html' %}
{% block title %}Access Denied{% endblock %}
{% block content %}
<div class="text-center">
    <h1>403 - Access Denied</h1>
    <p>You don't have permission to access this page.</p>
    <a href="{{ url_for('index') }}" class="btn btn-primary">Return to Dashboard</a>
</div>
{% endblock %}
```

## Best Practices

### 1. Always Pair with @login_required
```python
# ✅ CORRECT
@app.route('/admin')
@login_required
@feature_required('manage_users')
def admin_panel():
    pass

# ❌ WRONG - Missing @login_required
@app.route('/admin')
@feature_required('manage_users')
def admin_panel():
    pass
```

### 2. Match Template Visibility
If a link is hidden in templates with `{% if has_feature('view_reports') %}`, protect the route:
```python
@reports_bp.route('/')
@login_required
@feature_required('view_reports')
def list_reports():
    pass
```

### 3. Use Specific Features
```python
# ✅ GOOD - Specific feature
@feature_required('approve_relief_requests')

# ❌ AVOID - Too broad
@feature_required('view_dashboard')
```

### 4. Protect API Endpoints
```python
@api_bp.route('/inventory/update', methods=['POST'])
@login_required
@feature_required('manage_inventory')
def update_inventory_api():
    return jsonify({'status': 'success'})
```

## Testing Decorators

### Manual Testing
1. Log in as different role users
2. Try accessing protected routes
3. Verify appropriate error messages

### Test Accounts
- `test.logistics@odpem.gov.jm` - Logistics features
- `test.agency@gmail.com` - Agency features
- `test.director@odpem.gov.jm` - Director features
- `admin [at] odpem [dot] gov [dot] jm` - Full access

### Expected Results
| User Role | Route | Expected Result |
|-----------|-------|----------------|
| Logistics | `/inventory` | ✅ Access granted |
| Agency | `/inventory` | ❌ 403 Forbidden |
| Admin | `/inventory` | ✅ Access granted |

## Migration Guide

### Converting Existing Routes
Before:
```python
@items_bp.route('/')
@login_required
def list_items():
    # Anyone logged in can access
    pass
```

After:
```python
@items_bp.route('/')
@login_required
@feature_required('view_items')
def list_items():
    # Only users with view_items feature
    pass
```

### Rollout Strategy
1. Start with admin/critical routes
2. Test with each role
3. Gradually apply to all protected routes
4. Update navigation to hide inaccessible links

## Troubleshooting

### Issue: "Feature key not found"
**Solution:** Ensure feature key exists in `FeatureRegistry.FEATURES`

### Issue: Decorator not working
**Checklist:**
- ✅ Import decorator at top of file
- ✅ Place `@login_required` before `@feature_required`
- ✅ Use correct feature key (case-sensitive)
- ✅ Restart workflow after adding decorator

### Issue: All users getting 403
**Solution:** Check feature-to-role mapping in FeatureRegistry. Ensure roles are properly assigned.

## Security Notes

1. **Defense in Depth:** These decorators are backend protection. Template-level hiding is UI convenience, not security.
2. **Feature Keys:** Keep feature keys consistent between FeatureRegistry, decorators, and templates.
3. **API Protection:** Always protect API endpoints - they bypass template checks.
4. **Audit:** All 403 errors are logged. Monitor for suspicious access attempts.

## Summary

- ✅ Use `@feature_required()` for feature-based access control
- ✅ Always pair with `@login_required`
- ✅ Match template visibility checks
- ✅ Test with different role accounts
- ✅ Protect both web routes and API endpoints
