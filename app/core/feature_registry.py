"""
Feature Access Registry for DRIMS

This module provides centralized feature-to-role mapping for the entire application.
It controls access to features across dashboards, navigation, profiles, and backend routes.

VERIFIED Role Codes (from database):
- SYSTEM_ADMINISTRATOR: System Administrator
- LOGISTICS_MANAGER: Logistics Manager  
- LOGISTICS_OFFICER: Logistics Officer
- ODPEM_DG: Director General
- ODPEM_DDG: Deputy Director General
- ODPEM_DIR_PEOD: Director, PEOD
- AGENCY_DISTRIBUTOR: Agency (Distributor)
- AGENCY_SHELTER: Agency (Shelter)
- INVENTORY_CLERK: Inventory Clerk
- AUDITOR: Auditor

Feature Categories:
- Relief Request Management
- Eligibility Review
- Package Fulfillment
- Inventory Management
- Master Data Management
- Reporting & Analytics
- User & Account Management
- System Notifications

Usage:
    from app.core.feature_registry import FeatureRegistry
    
    if FeatureRegistry.has_access(current_user, 'relief_request_creation'):
        # Show create request button
    
    features = FeatureRegistry.get_dashboard_features(current_user)
    # Returns list of features for user's dashboard
"""

from typing import List, Dict, Optional, Set
from app.core.rbac import EXECUTIVE_ROLES, LOGISTICS_ROLES, AGENCY_ROLES


class FeatureRegistry:
    """
    Centralized registry mapping features to roles, URLs, and UI components.
    This is the single source of truth for feature access control.
    
    Updated: 2025-11-14 - Verified against actual database role codes and blueprint routes
    """
    
    # Blueprint route names for url_for() - these are the actual route identifiers
    ROUTES = {
        # Relief Requests
        'relief_request_list': 'requests.list_requests',
        'relief_request_create': 'requests.create_request',
        'relief_request_view': 'requests.view_request',
        
        # Eligibility  
        'eligibility_pending': 'eligibility.pending_list',
        'eligibility_review': 'eligibility.review_request',
        
        # Packaging
        'packaging_pending_fulfillment': 'packaging.pending_fulfillment',
        'packaging_prepare': 'packaging.prepare_package',
        'packaging_pending_approval': 'packaging.pending_approval',
        'packaging_review_approval': 'packaging.review_approval',
        'dispatch_awaiting': 'packaging.awaiting_dispatch',
        'dispatch_received': 'packaging.dispatch_received',
        'dispatch_details': 'packaging.dispatch_details',
        'dispatch_received_details': 'packaging.dispatch_received_details',
        
        # Inventory
        'inventory_list': 'inventory.list_inventory',
        'intake_list': 'intake.list_intakes',
        'transfers_list': 'transfers.list_transfers',
        
        # Master Data
        'warehouses_list': 'warehouses.list_warehouses',
        'items_list': 'items.list_items',
        'events_list': 'events.list_events',
        'agencies_list': 'agencies.list_agencies',
        'donors_list': 'donors.list_donors',
        'donations_list': 'donations.list_donations',
        'custodians_list': 'custodians.list_custodians',
        
        # Reports
        'reports_main': 'reports.index',
        'reports_inventory': 'reports.inventory_summary',
        'reports_donations': 'reports.donations_summary',
        'donations_analytics': 'dashboard.donations_analytics',
        'relief_package_analytics': 'dashboard.relief_package_analytics',
        'aid_movement_dashboard': 'dashboard.aid_movement_dashboard',
        
        # Admin
        'users_list': 'user_admin.index',
        'account_requests_list': 'account_requests.list_requests',
        
        # Notifications
        'notifications_list': 'notifications.index',
        
        # Dashboards
        'director_dashboard': 'director.dashboard',
        'main_dashboard': 'dashboard.index',
    }
    
    FEATURES = {
        # =================================================================
        # RELIEF REQUEST MANAGEMENT (Agency Users)
        # =================================================================
        # REMOVED: 'relief_request_creation' - Consolidated into 'create_request_on_behalf'
        # 'relief_request_creation': {
        #     'name': 'Create Relief Requests',
        #     'description': 'Submit new relief requests for disaster events',
        #     'roles': ['AGENCY_DISTRIBUTOR', 'AGENCY_SHELTER', 'LOGISTICS_MANAGER', 'LOGISTICS_OFFICER'],
        #     'route': 'requests.create_request',
        #     'url': '/relief-requests/create',  # Fallback if route fails
        #     'icon': 'bi-plus-circle',
        #     'category': 'relief_requests',
        #     'dashboard_widget': 'create_request_card',
        #     'navigation_group': 'relief_requests',
        #     'priority': 10
        # },
        'relief_request_tracking': {
            'name': 'Track My Requests',
            'description': 'View and track status of submitted relief requests',
            'roles': ['AGENCY_DISTRIBUTOR', 'AGENCY_SHELTER'],
            'route': 'requests.list_requests',
            'url': '/relief-requests',
            'icon': 'bi-list-check',
            'category': 'relief_requests',
            'dashboard_widget': 'my_requests_widget',
            'navigation_group': 'relief_requests',
            'priority': 9
        },
        
        # =================================================================
        # ELIGIBILITY REVIEW (ODPEM Executives - DG, DDG, Dir PEOD)
        # =================================================================
        'eligibility_review': {
            'name': 'Review Relief Requests',
            'description': 'Review and approve/deny relief request eligibility',
            'roles': list(EXECUTIVE_ROLES),
            'route': 'eligibility.pending_list',
            'url': '/eligibility/pending',
            'icon': 'bi-clipboard-check',
            'category': 'eligibility',
            'dashboard_widget': 'pending_eligibility_widget',
            'navigation_group': 'eligibility',
            'priority': 20
        },
        'director_dashboard': {
            'name': 'Executive Dashboard',
            'description': 'Unified dashboard for ODPEM executives',
            'roles': list(EXECUTIVE_ROLES),
            'route': 'director.dashboard',
            'url': '/director/dashboard',
            'icon': 'bi-speedometer2',
            'category': 'eligibility',
            'dashboard_widget': 'director_overview',
            'priority': 25
        },
        'operations_dashboard': {
            'name': 'Operations Dashboard',
            'description': 'Executive performance metrics for donations and relief fulfillment',
            'roles': list(EXECUTIVE_ROLES),
            'route': 'operations_dashboard.index',
            'url': '/executive/operations',
            'icon': 'bi-graph-up',
            'category': 'analytics',
            'dashboard_widget': None,
            'navigation_group': 'dashboard',
            'priority': 24
        },
        'funds_donations_report': {
            'name': 'Funds Donations Report',
            'description': 'View all monetary donations received',
            'roles': list(EXECUTIVE_ROLES) + ['LOGISTICS_MANAGER'],
            'route': 'reports.funds_donations',
            'url': '/reports/funds_donations',
            'icon': 'bi-currency-dollar',
            'category': 'reports',
            'dashboard_widget': None,
            'navigation_group': 'reports',
            'priority': 23
        },
        
        # =================================================================
        # PACKAGE FULFILLMENT (Logistics Officers & Managers)
        # Verified: packaging.py shows is_logistics_officer() OR is_logistics_manager()
        # =================================================================
        'create_request_on_behalf': {
            'name': 'Create Request (On Behalf of Agency)',
            'description': 'Create relief requests on behalf of agencies',
            'roles': ['AGENCY_DISTRIBUTOR', 'AGENCY_SHELTER', 'LOGISTICS_OFFICER', 'LOGISTICS_MANAGER'],
            'route': 'requests.list_requests',
            'url': '/relief-requests',
            'icon': 'bi-plus-circle-fill',
            'category': 'relief_requests',
            'navigation_group': 'relief_requests',
            'priority': 10
        },
        'package_preparation': {
            'name': 'Relief Fulfillment Packages',
            'description': 'Allocate inventory and prepare relief packages',
            'roles': ['LOGISTICS_OFFICER', 'LOGISTICS_MANAGER'],
            'route': 'packaging.pending_fulfillment',
            'url': '/packaging/pending-fulfillment',
            'icon': 'bi-box-seam',
            'category': 'packaging',
            'dashboard_widget': 'pending_fulfillment_widget',
            'navigation_group': 'packaging',
            'priority': 15
        },
        'dispatch_awaiting': {
            'name': 'Awaiting Dispatch',
            'description': 'Process packages awaiting handover to agencies',
            'roles': ['INVENTORY_CLERK'],
            'route': 'packaging.awaiting_dispatch',
            'url': '/packaging/dispatch/awaiting',
            'icon': 'bi-truck',
            'category': 'packaging',
            'dashboard_widget': 'awaiting_dispatch_widget',
            'navigation_group': 'packaging',
            'priority': 17
        },
        'dispatch_received': {
            'name': 'Dispatch Received',
            'description': 'View packages handed over to agencies',
            'roles': ['LOGISTICS_OFFICER', 'LOGISTICS_MANAGER'],
            'route': 'packaging.dispatch_received',
            'url': '/packaging/dispatch/received',
            'icon': 'bi-check2-square',
            'category': 'packaging',
            'dashboard_widget': 'dispatch_received_widget',
            'navigation_group': 'packaging',
            'priority': 19
        },
        
        # =================================================================
        # INVENTORY MANAGEMENT
        # Verified: Most inventory routes only require @login_required
        # =================================================================
        'inventory_view': {
            'name': 'View Inventory',
            'description': 'View current stock levels across warehouses',
            'roles': list(LOGISTICS_ROLES) + ['INVENTORY_CLERK'] + list(EXECUTIVE_ROLES) + ['SYSTEM_ADMINISTRATOR'],
            'route': 'inventory.list_inventory',
            'url': '/inventory',
            'icon': 'bi-boxes',
            'category': 'inventory',
            'dashboard_widget': 'inventory_summary_widget',
            'navigation_group': 'inventory',
            'priority': 12
        },
        
        # =================================================================
        # MASTER DATA MANAGEMENT
        # =================================================================
        'warehouse_management': {
            'name': 'Manage Warehouses',
            'description': 'Create and manage warehouse locations',
            'roles': ['CUSTODIAN'],  # Restricted to CUSTODIAN only - master data table
            'route': 'warehouses.list_warehouses',
            'url': '/warehouses',
            'icon': 'bi-building',
            'category': 'master_data',
            'navigation_group': 'master_data',
            'priority': 5
        },
        'item_category_management': {
            'name': 'Item Categories',
            'description': 'Manage item categories for relief supplies',
            'roles': ['CUSTODIAN'],  # Restricted to CUSTODIAN only - master data table
            'route': 'item_categories.list_categories',
            'url': '/item-categories',
            'icon': 'bi-grid-3x3',
            'category': 'master_data',
            'navigation_group': 'master_data',
            'priority': 4
        },
        'uom_management': {
            'name': 'Units of Measure',
            'description': 'Manage units of measure for items and inventory',
            'roles': ['CUSTODIAN'],  # Restricted to CUSTODIAN only - master data table
            'route': 'uom.list_uom',
            'url': '/uom',
            'icon': 'bi-rulers',
            'category': 'master_data',
            'navigation_group': 'master_data',
            'priority': 3
        },
        'item_management': {
            'name': 'Manage Items',
            'description': 'Manage relief item catalog',
            'roles': ['CUSTODIAN'],  # Restricted to CUSTODIAN only - master data table
            'route': 'items.list_items',
            'url': '/items',
            'icon': 'bi-box-seam',
            'category': 'master_data',
            'navigation_group': 'master_data',
            'priority': 3
        },
        'event_management': {
            'name': 'Disaster Events',
            'description': 'Manage disaster events and their lifecycle',
            'roles': ['CUSTODIAN'],  # Restricted to CUSTODIAN only - other master tables will follow later
            'route': 'events.list_events',
            'url': '/events',
            'icon': 'bi-calendar-event',
            'category': 'master_data',
            'navigation_group': 'master_data',
            'priority': 8
        },
        'agency_management': {
            'name': 'Manage Agencies',
            'description': 'Manage relief agencies (Custodian-only)',
            'roles': ['CUSTODIAN'],  # Restricted to CUSTODIAN only - master data table
            'route': 'agencies.list_agencies',
            'url': '/agencies',
            'icon': 'bi-shop',
            'category': 'master_data',
            'navigation_group': 'master_data',
            'priority': 6
        },
        'donor_management': {
            'name': 'Manage Donors',
            'description': 'Manage donor information',
            'roles': ['CUSTODIAN'],  # Restricted to CUSTODIAN only - master data table
            'route': 'donors.list_donors',
            'url': '/donors',
            'icon': 'bi-people',
            'category': 'master_data',
            'navigation_group': 'master_data',
            'priority': 7
        },
        'custodian_management': {
            'name': 'Manage Custodians',
            'description': 'Manage custodian records (ODPEM, etc.)',
            'roles': ['CUSTODIAN'],
            'route': 'custodians.list_custodians',
            'url': '/custodians',
            'icon': 'bi-shield-check',
            'category': 'master_data',
            'navigation_group': 'master_data',
            'priority': 6
        },
        'donation_management': {
            'name': 'Donations',
            'description': 'Accept and process donations',
            'roles': ['LOGISTICS_OFFICER', 'LOGISTICS_MANAGER'],
            'route': 'donations.list_donations',
            'url': '/donations',
            'icon': 'bi-gift',
            'category': 'inventory',
            'navigation_group': 'inventory',
            'priority': 3
        },
        'donation_verification': {
            'name': 'Verify Donations',
            'description': 'Review and verify entered donations',
            'roles': ['LOGISTICS_MANAGER'],
            'route': 'donations.verify_list',
            'url': '/donations/verify',
            'icon': 'bi-clipboard-check',
            'category': 'inventory',
            'priority': 3
        },
        'donation_intake_management': {
            'name': 'Donation Intake',
            'description': 'Intake verified donations into warehouse inventory',
            'roles': ['LOGISTICS_OFFICER', 'LOGISTICS_MANAGER'],
            'route': 'donation_intake.list_intakes',
            'url': '/donation-intake',
            'icon': 'bi-box-arrow-in-down',
            'category': 'inventory',
            'navigation_group': 'inventory',
            'priority': 4
        },
        'donation_intake_verification': {
            'name': 'Verify Donation Intakes',
            'description': 'Review and verify submitted donation intakes',
            'roles': ['LOGISTICS_MANAGER'],
            'route': 'donation_intake.verify_list',
            'url': '/donation-intake/verify',
            'icon': 'bi-clipboard2-check',
            'category': 'inventory',
            'priority': 4
        },
        
        # =================================================================
        # REPORTING & ANALYTICS
        # =================================================================
        'reports_main': {
            'name': 'Reports',
            'description': 'Access system reports',
            'roles': list(LOGISTICS_ROLES) + list(EXECUTIVE_ROLES) + ['SYSTEM_ADMINISTRATOR'],
            'route': 'reports.index',
            'url': '/reports',
            'icon': 'bi-file-earmark-bar-graph',
            'category': 'reports',
            'navigation_group': 'reports',
            'priority': 2
        },
        'reports_inventory': {
            'name': 'Inventory Reports',
            'description': 'View inventory summary reports',
            'roles': list(LOGISTICS_ROLES) + list(EXECUTIVE_ROLES) + ['SYSTEM_ADMINISTRATOR'],
            'route': 'reports.inventory_summary',
            'url': '/reports/inventory_summary',
            'icon': 'bi-bar-chart',
            'category': 'reports',
            'dashboard_widget': 'inventory_report_link',
            'priority': 2
        },
        'reports_donations': {
            'name': 'Donation Reports',
            'description': 'View donations summary reports',
            'roles': ['LOGISTICS_MANAGER'] + list(EXECUTIVE_ROLES) + ['SYSTEM_ADMINISTRATOR'],
            'route': 'reports.donations_summary',
            'url': '/reports/donations_summary',
            'icon': 'bi-graph-up',
            'category': 'reports',
            'dashboard_widget': 'donation_report_link',
            'priority': 2
        },
        'donations_analytics': {
            'name': 'Donation Analytics',
            'description': 'Interactive analytics dashboard for donation metrics and trends',
            'roles': list(EXECUTIVE_ROLES) + ['LOGISTICS_MANAGER'],
            'route': 'dashboard.donations_analytics',
            'url': '/dashboard/donations-analytics',
            'icon': 'bi-graph-up-arrow',
            'category': 'dashboard',
            'navigation_group': 'dashboard',
            'priority': 5
        },
        'relief_package_analytics': {
            'name': 'Relief Package Analytics',
            'description': 'Analytics dashboard for dispatched relief packages to shelters and distributors',
            'roles': list(EXECUTIVE_ROLES) + ['LOGISTICS_MANAGER'],
            'route': 'dashboard.relief_package_analytics',
            'url': '/dashboard/relief-package-analytics',
            'icon': 'bi-box-arrow-up-right',
            'category': 'dashboard',
            'navigation_group': 'dashboard',
            'priority': 6
        },
        'aid_movement_dashboard': {
            'name': 'Aid Movement Dashboard',
            'description': 'View aid movement totals: received, issued, and in store across warehouses',
            'roles': list(EXECUTIVE_ROLES) + ['LOGISTICS_MANAGER'],
            'route': 'dashboard.aid_movement_dashboard',
            'url': '/dashboard/aid-movement',
            'icon': 'bi-arrow-left-right',
            'category': 'dashboard',
            'navigation_group': 'dashboard',
            'priority': 7
        },
        'aid_item_movement_detail': {
            'name': 'Item Distribution Dashboard',
            'description': 'Drill-down view of aid movement for a specific item across warehouses',
            'roles': list(EXECUTIVE_ROLES) + ['LOGISTICS_MANAGER'],
            'route': 'dashboard.aid_item_movement_detail',
            'url': '/dashboard/aid-movement/item-detail',
            'icon': 'bi-box-arrow-in-down-right',
            'category': 'dashboard',
            'navigation_group': 'dashboard',
            'priority': 8
        },
        
        # =================================================================
        # USER & ACCOUNT MANAGEMENT
        # =================================================================
        'user_management': {
            'name': 'Manage Users',
            'description': 'Create and manage user accounts',
            'roles': ['SYSTEM_ADMINISTRATOR', 'CUSTODIAN'],
            'route': 'user_admin.index',
            'url': '/users',
            'icon': 'bi-person-gear',
            'category': 'admin',
            'navigation_group': 'admin',
            'priority': 1
        },
        'account_requests': {
            'name': 'Review Account Requests',
            'description': 'Review and approve agency account requests',
            'roles': ['SYSTEM_ADMINISTRATOR'],
            'route': 'account_requests.list_requests',
            'url': '/account-requests',
            'icon': 'bi-person-plus',
            'category': 'admin',
            'dashboard_widget': 'pending_account_requests',
            'navigation_group': 'admin',
            'priority': 1
        },
        
        # =================================================================
        # NOTIFICATIONS
        # =================================================================
        'notifications': {
            'name': 'Notifications',
            'description': 'View system notifications',
            'roles': list(LOGISTICS_ROLES) + list(EXECUTIVE_ROLES) + list(AGENCY_ROLES) + ['INVENTORY_CLERK', 'SYSTEM_ADMINISTRATOR'],
            'route': 'notifications.index',
            'url': '/notifications',
            'icon': 'bi-bell',
            'category': 'notifications',
            'navigation_group': 'user',
            'priority': 30
        },
        
        # =================================================================
        # DASHBOARD VIEWS (Role-specific landing pages)
        # =================================================================
        'logistics_dashboard': {
            'name': 'Logistics Dashboard',
            'description': 'Logistics operations overview',
            'roles': ['LOGISTICS_OFFICER', 'LOGISTICS_MANAGER'],
            'route': 'dashboard.index',
            'url': '/dashboard',
            'icon': 'bi-speedometer2',
            'category': 'dashboard',
            'navigation_group': 'dashboard',
            'is_dashboard': True,
            'priority': 100
        },
        'agency_dashboard': {
            'name': 'Agency Dashboard',
            'description': 'Agency relief request overview',
            'roles': ['AGENCY_DISTRIBUTOR', 'AGENCY_SHELTER'],
            'route': 'dashboard.index',
            'url': '/dashboard',
            'icon': 'bi-speedometer2',
            'category': 'dashboard',
            'navigation_group': 'dashboard',
            'is_dashboard': True,
            'priority': 100
        },
        'admin_dashboard': {
            'name': 'Admin Dashboard',
            'description': 'System administration overview',
            'roles': ['SYSTEM_ADMINISTRATOR'],
            'route': 'dashboard.index',
            'url': '/dashboard',
            'icon': 'bi-speedometer2',
            'category': 'dashboard',
            'navigation_group': 'dashboard',
            'is_dashboard': True,
            'priority': 100
        },
        'lo_dashboard': {
            'name': 'My Activity Dashboard',
            'description': 'Personal activity dashboard for Logistics Officers with charts and metrics',
            'roles': ['LOGISTICS_OFFICER'],
            'route': 'dashboard.lo_dashboard',
            'url': '/dashboard/lo',
            'icon': 'bi-person-badge',
            'category': 'logistics',
            'dashboard_widget': 'lo_overview',
            'navigation_group': 'logistics',
            'is_dashboard': False,
            'priority': 45
        },
    }
    
    @classmethod
    def get_user_role_codes(cls, user) -> Set[str]:
        """
        Extract role codes from a user object.
        
        Args:
            user: User object with roles relationship
            
        Returns:
            Set of role code strings
        """
        if not user or not hasattr(user, 'roles'):
            return set()
        return {role.code for role in user.roles}
    
    @classmethod
    def has_access(cls, user, feature_key: str) -> bool:
        """
        Check if a user has access to a specific feature.
        
        Args:
            user: User object with roles
            feature_key: Feature identifier from FEATURES dict
            
        Returns:
            True if user has any role that grants access to the feature
        """
        if feature_key not in cls.FEATURES:
            return False
        
        user_roles = cls.get_user_role_codes(user)
        feature_roles = set(cls.FEATURES[feature_key]['roles'])
        
        return bool(user_roles & feature_roles)
    
    @classmethod
    def get_accessible_features(cls, user) -> List[Dict]:
        """
        Get all features accessible to a user.
        
        Args:
            user: User object with roles
            
        Returns:
            List of feature dictionaries the user can access
        """
        user_roles = cls.get_user_role_codes(user)
        accessible = []
        
        for key, feature in cls.FEATURES.items():
            feature_roles = set(feature['roles'])
            if user_roles & feature_roles:
                accessible.append({
                    'key': key,
                    **feature
                })
        
        return accessible
    
    @classmethod
    def get_dashboard_features(cls, user) -> List[Dict]:
        """
        Get features that should appear on user's dashboard.
        
        Args:
            user: User object with roles
            
        Returns:
            List of features with dashboard widgets, sorted by priority
        """
        accessible = cls.get_accessible_features(user)
        dashboard_features = [
            f for f in accessible 
            if 'dashboard_widget' in f and f['dashboard_widget']
        ]
        
        return sorted(dashboard_features, key=lambda x: x.get('priority', 999), reverse=True)
    
    @classmethod
    def get_navigation_features(cls, user, group: Optional[str] = None) -> List[Dict]:
        """
        Get features for navigation menu.
        
        Args:
            user: User object with roles
            group: Optional navigation group filter
            
        Returns:
            List of features for navigation, sorted by priority
        """
        accessible = cls.get_accessible_features(user)
        
        if group:
            nav_features = [
                f for f in accessible 
                if f.get('navigation_group') == group
            ]
        else:
            nav_features = [f for f in accessible if 'navigation_group' in f]
        
        return sorted(nav_features, key=lambda x: x.get('priority', 999), reverse=True)
    
    @classmethod
    def get_features_by_category(cls, user, category: str) -> List[Dict]:
        """
        Get features by category.
        
        Args:
            user: User object with roles
            category: Feature category
            
        Returns:
            List of features in the category
        """
        accessible = cls.get_accessible_features(user)
        return [f for f in accessible if f.get('category') == category]
    
    @classmethod
    def get_primary_role(cls, user) -> Optional[str]:
        """
        Determine user's primary role based on priority.
        
        Priority order (highest to lowest):
        1. SYSTEM_ADMINISTRATOR
        2. EXECUTIVE_ROLES (DG, DDG, Dir PEOD) - Eligibility approval
        3. CUSTODIAN
        4. LOGISTICS_MANAGER
        5. LOGISTICS_OFFICER
        6. INVENTORY_CLERK
        7. AGENCY_ROLES (Distributor, Shelter)
        
        Args:
            user: User object with roles
            
        Returns:
            Primary role code or None
        """
        ROLE_PRIORITY = (
            ['SYSTEM_ADMINISTRATOR'] +
            list(EXECUTIVE_ROLES) +
            ['CUSTODIAN'] +
            list(LOGISTICS_ROLES) +
            ['INVENTORY_CLERK'] +
            list(AGENCY_ROLES) +
            ['AUDITOR']
        )
        
        user_roles = cls.get_user_role_codes(user)
        
        for role in ROLE_PRIORITY:
            if role in user_roles:
                return role
        
        return list(user_roles)[0] if user_roles else None
    
    @classmethod
    def get_role_display_name(cls, role_code: str) -> str:
        """
        Get human-readable name for a role code.
        
        Args:
            role_code: Role code string
            
        Returns:
            Display name for the role
        """
        ROLE_NAMES = {
            'SYSTEM_ADMINISTRATOR': 'System Administrator',
            'ODPEM_DG': 'Director General',
            'ODPEM_DDG': 'Deputy Director General',
            'ODPEM_DIR_PEOD': 'Director, PEOD',
            'LOGISTICS_MANAGER': 'Logistics Manager',
            'LOGISTICS_OFFICER': 'Logistics Officer',
            'INVENTORY_CLERK': 'Inventory Clerk',
            'AGENCY_DISTRIBUTOR': 'Agency (Distributor)',
            'AGENCY_SHELTER': 'Agency (Shelter)',
            'AUDITOR': 'Auditor'
        }
        return ROLE_NAMES.get(role_code, role_code)
