"""
Dashboard Service for DRIMS

Provides feature-driven dashboard logic for generating role-specific widgets,
metric cards, and dashboard content based on the Feature Access Registry.

This service layer sits between the Feature Registry and the dashboard templates,
providing business logic for dashboard rendering.
"""

from typing import List, Dict, Optional
from flask import url_for
from app.core.feature_registry import FeatureRegistry
from app.db.models import ReliefRqst, ReliefPkg, Notification
from app.db import db
from sqlalchemy import func, and_


class DashboardService:
    """Service for generating role-specific dashboard content."""
    
    @staticmethod
    def get_dashboard_data(user) -> Dict:
        """
        Get complete dashboard data for a user based on their roles.
        
        Args:
            user: Current user object with roles
            
        Returns:
            Dictionary containing:
            - features: List of accessible features
            - widgets: List of widget data
            - metrics: Summary metrics
            - primary_role: User's primary role
            - role_display_name: Human-readable role name
        """
        primary_role = FeatureRegistry.get_primary_role(user)
        
        return {
            'features': FeatureRegistry.get_accessible_features(user),
            'dashboard_features': FeatureRegistry.get_dashboard_features(user),
            'widgets': DashboardService._get_widgets_for_user(user),
            'metrics': DashboardService._get_metrics_for_user(user),
            'primary_role': primary_role,
            'role_display_name': FeatureRegistry.get_role_display_name(primary_role) if primary_role else 'User',
            'quick_actions': DashboardService._get_quick_actions(user),
        }
    
    @staticmethod
    def _get_widgets_for_user(user) -> List[Dict]:
        """
        Generate widget data for user's dashboard.
        
        Returns list of widgets with:
        - widget_id: Unique identifier
        - title: Widget title
        - data: Widget-specific data
        - template: Template file to render
        - priority: Display priority
        """
        widgets = []
        user_roles = FeatureRegistry.get_user_role_codes(user)
        
        # Agency users: My Requests widget
        if user_roles & {'AGENCY_DISTRIBUTOR', 'AGENCY_SHELTER'}:
            widgets.append(DashboardService._build_my_requests_widget(user))
        
        # ODPEM Directors: Eligibility Review widget
        if user_roles & {'ODPEM_DG', 'ODPEM_DDG', 'ODPEM_DIR_PEOD'}:
            widgets.append(DashboardService._build_eligibility_widget(user))
        
        # Logistics: Fulfillment widgets
        if user_roles & {'LOGISTICS_OFFICER', 'LOGISTICS_MANAGER'}:
            widgets.append(DashboardService._build_fulfillment_widget(user))
            if 'LOGISTICS_MANAGER' in user_roles:
                widgets.append(DashboardService._build_approval_widget(user))
        
        # All authenticated users: Notifications widget
        widgets.append(DashboardService._build_notifications_widget(user))
        
        return sorted(widgets, key=lambda w: w.get('priority', 999), reverse=True)
    
    @staticmethod
    def _build_my_requests_widget(user) -> Dict:
        """Build My Requests widget for agency users."""
        # Get user's agency relief requests
        requests = ReliefRqst.query.filter_by(
            agency_id=user.agency_id
        ).order_by(ReliefRqst.create_dtime.desc()).limit(5).all()
        
        return {
            'widget_id': 'my_requests',
            'title': 'My Recent Requests',
            'icon': 'bi-list-check',
            'data': {
                'requests': requests,
                'total_count': ReliefRqst.query.filter_by(agency_id=user.agency_id).count()
            },
            'action_url': url_for('requests.list_requests'),
            'action_label': 'View All Requests',
            'priority': 20
        }
    
    @staticmethod
    def _build_eligibility_widget(user) -> Dict:
        """Build Eligibility Review widget for directors."""
        # Status 1 = Awaiting Approval
        pending_count = ReliefRqst.query.filter_by(status_code=1).count()
        
        return {
            'widget_id': 'pending_eligibility',
            'title': 'Pending Eligibility Reviews',
            'icon': 'bi-clipboard-check',
            'data': {
                'pending_count': pending_count,
                'badge_variant': 'warning' if pending_count > 0 else 'success'
            },
            'action_url': url_for('eligibility.pending_list'),
            'action_label': 'Review Requests',
            'priority': 25
        }
    
    @staticmethod
    def _build_fulfillment_widget(user) -> Dict:
        """Build Fulfillment widget for logistics."""
        # Status 3 = Submitted (approved, awaiting fulfillment)
        pending_count = ReliefRqst.query.filter_by(status_code=3).count()
        
        return {
            'widget_id': 'pending_fulfillment',
            'title': 'Pending Fulfillment',
            'icon': 'bi-box-seam',
            'data': {
                'pending_count': pending_count,
                'badge_variant': 'info' if pending_count > 0 else 'success'
            },
            'action_url': url_for('packaging.pending_fulfillment'),
            'action_label': 'Prepare Packages',
            'priority': 22
        }
    
    @staticmethod
    def _build_approval_widget(user) -> Dict:
        """Build Package Approval widget for logistics managers."""
        # Status P = Pending Approval
        pending_count = ReliefPkg.query.filter_by(status_code='P').count()
        
        return {
            'widget_id': 'pending_approval',
            'title': 'Packages Awaiting Approval',
            'icon': 'bi-check-circle',
            'data': {
                'pending_count': pending_count,
                'badge_variant': 'warning' if pending_count > 0 else 'success'
            },
            'action_url': url_for('packaging.pending_approval'),
            'action_label': 'Review Packages',
            'priority': 24
        }
    
    @staticmethod
    def _build_notifications_widget(user) -> Dict:
        """Build Notifications widget for all users."""
        unread_count = Notification.query.filter_by(
            user_id=user.user_id,
            status='unread'
        ).count()
        
        return {
            'widget_id': 'notifications',
            'title': 'Recent Notifications',
            'icon': 'bi-bell',
            'data': {
                'unread_count': unread_count,
                'badge_variant': 'danger' if unread_count > 0 else 'secondary'
            },
            'action_url': url_for('notifications.index'),
            'action_label': 'View All',
            'priority': 5
        }
    
    @staticmethod
    def _get_metrics_for_user(user) -> Dict:
        """
        Calculate summary metrics for user's dashboard.
        
        Returns role-specific metrics like:
        - Total requests (agency)
        - Pending reviews (director)
        - Inventory levels (logistics)
        """
        metrics = {}
        user_roles = FeatureRegistry.get_user_role_codes(user)
        
        # Agency metrics
        if user_roles & {'AGENCY_DISTRIBUTOR', 'AGENCY_SHELTER'}:
            metrics.update({
                'total_requests': ReliefRqst.query.filter_by(agency_id=user.agency_id).count(),
                'pending_requests': ReliefRqst.query.filter(
                    ReliefRqst.agency_id == user.agency_id,
                    ReliefRqst.status_code.in_([0, 1])
                ).count(),
                'fulfilled_requests': ReliefRqst.query.filter_by(
                    agency_id=user.agency_id,
                    status_code=7
                ).count(),
            })
        
        # Director metrics
        if user_roles & {'ODPEM_DG', 'ODPEM_DDG', 'ODPEM_DIR_PEOD'}:
            metrics.update({
                'pending_reviews': ReliefRqst.query.filter_by(status_code=1).count(),
                'approved_requests': ReliefRqst.query.filter_by(status_code=3).count(),
                'total_active_requests': ReliefRqst.query.filter(
                    ReliefRqst.status_code.in_([1, 3, 5])
                ).count(),
            })
        
        # Logistics metrics
        if user_roles & {'LOGISTICS_OFFICER', 'LOGISTICS_MANAGER'}:
            metrics.update({
                'pending_fulfillment': ReliefRqst.query.filter_by(status_code=3).count(),
                'in_progress': ReliefRqst.query.filter_by(status_code=5).count(),
                'pending_approval': ReliefPkg.query.filter_by(status_code='P').count() if 'LOGISTICS_MANAGER' in user_roles else 0,
            })
        
        return metrics
    
    @staticmethod
    def _get_quick_actions(user) -> List[Dict]:
        """
        Get quick action buttons for user's role.
        
        Returns list of actions with:
        - label: Button text
        - url: Action URL
        - icon: Bootstrap icon
        - variant: Button style
        """
        actions = []
        user_roles = FeatureRegistry.get_user_role_codes(user)
        
        # Agency quick actions
        if user_roles & {'AGENCY_DISTRIBUTOR', 'AGENCY_SHELTER'}:
            actions.append({
                'label': 'Create New Request',
                'url': url_for('requests.create_request'),
                'icon': 'bi-plus-circle',
                'variant': 'relief-primary'
            })
        
        # Director quick actions
        if user_roles & {'ODPEM_DG', 'ODPEM_DDG', 'ODPEM_DIR_PEOD'}:
            actions.extend([
                {
                    'label': 'Review Eligibility',
                    'url': url_for('eligibility.pending_list'),
                    'icon': 'bi-clipboard-check',
                    'variant': 'relief-primary'
                },
                {
                    'label': 'Director Dashboard',
                    'url': url_for('director.dashboard'),
                    'icon': 'bi-speedometer2',
                    'variant': 'relief-secondary'
                }
            ])
        
        # Logistics quick actions
        if user_roles & {'LOGISTICS_OFFICER', 'LOGISTICS_MANAGER'}:
            actions.append({
                'label': 'Prepare Packages',
                'url': url_for('packaging.pending_fulfillment'),
                'icon': 'bi-box-seam',
                'variant': 'relief-primary'
            })
            
            if 'LOGISTICS_MANAGER' in user_roles:
                actions.append({
                    'label': 'Review Approvals',
                    'url': url_for('packaging.pending_approval'),
                    'icon': 'bi-check-circle',
                    'variant': 'relief-secondary'
                })
        
        return actions
    
    @staticmethod
    def get_navigation_items(user, group: Optional[str] = None) -> List[Dict]:
        """
        Get navigation menu items for user based on accessible features.
        
        Args:
            user: Current user
            group: Optional navigation group filter
            
        Returns:
            List of navigation items with url, label, icon
        """
        features = FeatureRegistry.get_navigation_features(user, group)
        
        nav_items = []
        for feature in features:
            try:
                # Try to generate URL from route
                url = url_for(feature['route']) if feature.get('route') else feature.get('url')
            except:
                # Fallback to hardcoded URL
                url = feature.get('url', '#')
            
            nav_items.append({
                'label': feature['name'],
                'url': url,
                'icon': feature.get('icon', 'bi-circle'),
                'description': feature.get('description', '')
            })
        
        return nav_items
