"""
Status code helpers and mappings for DRIMS
"""

EVENT_STATUS = {
    'A': 'Active',
    'C': 'Closed'
}

ITEM_STATUS = {
    'A': 'Active',
    'I': 'Inactive'
}

WAREHOUSE_STATUS = {
    'A': 'Active',
    'I': 'Inactive'
}

INVENTORY_STATUS = {
    'A': 'Available',
    'U': 'Unavailable'
}

DONATION_STATUS = {
    'A': 'Accepted',
    'P': 'Pending',
    'C': 'Completed'
}

RELIEFRQST_STATUS = {
    0: 'Draft',
    1: 'Awaiting Approval',
    2: 'Cancelled',
    3: 'Submitted',
    4: 'Denied',
    5: 'Part Filled',
    6: 'Closed',
    7: 'Filled',
    8: 'Ineligible'
}

RELIEFRQST_ITEM_STATUS = {
    'R': 'Requested',
    'U': 'Unavailable',
    'W': 'Waiting',
    'D': 'Denied',
    'P': 'Partial',
    'L': 'Limited',
    'F': 'Fulfilled'
}

RELIEFPKG_STATUS = {
    'P': 'Pending',
    'D': 'Dispatched',
    'C': 'Completed'
}

INTAKE_STATUS = {
    'I': 'Incomplete',
    'C': 'Completed',
    'V': 'Verified'
}

URGENCY_IND = {
    'L': 'Low',
    'M': 'Medium',
    'H': 'High',
    'C': 'Critical'
}

DBINTAKE_ITEM_STATUS = {
    'P': 'Pending',
    'V': 'Verified'
}

NEEDS_LIST_STATUS = {
    'Draft': 'Draft',
    'Submitted': 'Submitted',
    'Under Review': 'Under Review',
    'Approved': 'Approved',
    'Rejected': 'Rejected',
    'In Fulfilment': 'In Fulfilment',
    'Completed': 'Completed'
}

NEEDS_LIST_PRIORITY = {
    'LOW': 'Low',
    'MEDIUM': 'Medium',
    'HIGH': 'High',
    'CRITICAL': 'Critical'
}

FULFILMENT_STATUS = {
    'In Preparation': 'In Preparation',
    'Ready': 'Ready',
    'Dispatched': 'Dispatched',
    'Received': 'Received',
    'Completed': 'Completed',
    'Cancelled': 'Cancelled'
}

DISTRIBUTION_PACKAGE_STATUS = {
    'Draft': 'Draft',
    'Approved': 'Approved',
    'Dispatched': 'Dispatched',
    'Delivered': 'Delivered',
    'Cancelled': 'Cancelled'
}

STATUS_BADGE_MAP = {
    'event': {'A': 'success', 'C': 'secondary'},
    'warehouse': {'A': 'success', 'I': 'secondary'},
    'item': {'A': 'success', 'I': 'secondary'},
    'inventory': {'A': 'success', 'I': 'secondary'},
    'donation': {'A': 'success', 'P': 'warning', 'C': 'secondary'},
    'reliefpkg': {'P': 'warning', 'D': 'primary', 'C': 'success'},
    'reliefrqst': {0: 'secondary', 1: 'warning', 2: 'secondary', 3: 'info', 4: 'danger', 5: 'warning', 6: 'secondary', 7: 'success', 8: 'danger'},
    'reliefrqst_item': {'R': 'info', 'U': 'danger', 'W': 'warning', 'D': 'danger', 'P': 'warning', 'L': 'info', 'F': 'success'},
    'urgency': {'L': 'secondary', 'M': 'info', 'H': 'warning', 'C': 'danger'},
    'dbintake': {'I': 'warning', 'C': 'success', 'V': 'primary'},
    'dbintake_item': {'P': 'warning', 'V': 'success'},
    'needs_list': {'Draft': 'secondary', 'Submitted': 'info', 'Under Review': 'warning', 'Approved': 'success', 'Rejected': 'danger', 'In Fulfilment': 'primary', 'Completed': 'success'},
    'needs_list_priority': {'LOW': 'secondary', 'MEDIUM': 'info', 'HIGH': 'warning', 'CRITICAL': 'danger'},
    'fulfilment': {'In Preparation': 'warning', 'Ready': 'info', 'Dispatched': 'primary', 'Received': 'success', 'Completed': 'success', 'Cancelled': 'secondary'},
    'distribution_package': {'Draft': 'secondary', 'Approved': 'info', 'Dispatched': 'primary', 'Delivered': 'success', 'Cancelled': 'danger'}
}

def get_status_label(status_code, status_type='event'):
    """Get human-readable status label"""
    mappings = {
        'event': EVENT_STATUS,
        'item': ITEM_STATUS,
        'warehouse': WAREHOUSE_STATUS,
        'inventory': INVENTORY_STATUS,
        'donation': DONATION_STATUS,
        'reliefrqst': RELIEFRQST_STATUS,
        'reliefrqst_item': RELIEFRQST_ITEM_STATUS,
        'reliefpkg': RELIEFPKG_STATUS,
        'intake': INTAKE_STATUS,
        'dbintake': INTAKE_STATUS,
        'dbintake_item': DBINTAKE_ITEM_STATUS,
        'urgency': URGENCY_IND,
        'needs_list': NEEDS_LIST_STATUS,
        'needs_list_priority': NEEDS_LIST_PRIORITY,
        'fulfilment': FULFILMENT_STATUS,
        'distribution_package': DISTRIBUTION_PACKAGE_STATUS
    }
    
    return mappings.get(status_type, {}).get(status_code, str(status_code))

def get_status_badge_class(status_code, status_type='event'):
    """Get Bootstrap badge class for status"""
    return STATUS_BADGE_MAP.get(status_type, {}).get(status_code, 'secondary')
