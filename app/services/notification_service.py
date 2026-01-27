"""
Centralized Notification Service for DRIMS

This service handles creation of in-app notifications with deep-linking support.
All notifications should use this service to ensure consistent URL generation and
proper permission handling.

Deep-Link URL Generation:
- Each notification includes a link_url field that navigates users directly to the relevant page
- URLs are generated using Flask's url_for() to ensure they're always correct
- Links respect user permissions - users won't see notifications for records they can't access

Usage Example:
    from app.services.notification_service import NotificationService
    
    NotificationService.create_relief_request_submitted_notification(
        relief_request=relief_request,
        recipient_users=odpem_directors
    )
"""

from flask import url_for
from app.db.models import Notification, User, ReliefRqst, ReliefPkg, Role
from app.db import db
from typing import List, Optional
from datetime import datetime


class NotificationService:
    """Centralized service for creating in-app notifications with deep links"""
    
    # Notification type constants
    TYPE_RELIEF_REQUEST_SUBMITTED = 'reliefrqst_submitted'
    TYPE_RELIEF_REQUEST_APPROVED = 'reliefrqst_approved'
    TYPE_RELIEF_REQUEST_DENIED = 'reliefrqst_denied'
    TYPE_PACKAGE_READY_FOR_APPROVAL = 'package_ready_for_approval'
    TYPE_PACKAGE_APPROVED = 'package_approved'
    TYPE_PACKAGE_DISPATCHED = 'package_dispatched'
    TYPE_PACKAGE_RECEIVED = 'package_received'
    TYPE_LOW_STOCK = 'low_stock'
    
    @staticmethod
    def get_active_users_by_role_codes(role_codes: List[str]) -> List[User]:
        """
        Get all active users with any of the specified role codes.
        Deduplicates users who may have multiple roles.
        
        Args:
            role_codes: List of role code strings (e.g., ['LOGISTICS_OFFICER', 'LOGISTICS_MANAGER'])
            
        Returns:
            List of unique active User objects
        """
        roles = Role.query.filter(Role.code.in_(role_codes)).all()
        users = []
        for role in roles:
            users.extend([u for u in role.users if u.is_active])
        
        # Remove duplicates by user_id
        return list({user.user_id: user for user in users}.values())
    
    @staticmethod
    def get_agency_active_users(agency_id: int) -> List[User]:
        """
        Get all active users for a specific agency.
        
        Args:
            agency_id: ID of the agency
            
        Returns:
            List of active User objects
        """
        return User.query.filter_by(
            agency_id=agency_id,
            is_active=True
        ).all()
    
    @staticmethod
    def create_notification(
        user_id: int,
        title: str,
        message: str,
        notification_type: str,
        link_url: str,
        reliefrqst_id: Optional[int] = None,
        warehouse_id: Optional[int] = None,
        payload: Optional[str] = None
    ) -> Notification:
        """
        Create a single notification with deep-link support.
        
        Args:
            user_id: ID of the user who will receive the notification
            title: Short notification title
            message: Detailed notification message
            notification_type: Type constant (e.g., TYPE_RELIEF_REQUEST_SUBMITTED)
            link_url: Deep-link URL to navigate to when clicked
            reliefrqst_id: Optional relief request ID for reference
            warehouse_id: Optional warehouse ID for reference
            payload: Optional JSON payload for additional data
            
        Returns:
            Created Notification object
        """
        from app.utils.timezone import now
        notification = Notification(
            user_id=user_id,
            reliefrqst_id=reliefrqst_id,
            warehouse_id=warehouse_id,
            title=title,
            message=message,
            type=notification_type,
            status='unread',
            link_url=link_url,
            payload=payload,
            is_archived=False,
            created_at=now()
        )
        db.session.add(notification)
        return notification
    
    @staticmethod
    def create_relief_request_submitted_notification(
        relief_request: ReliefRqst,
        recipient_users: List[User]
    ) -> List[Notification]:
        """
        Create notifications for ODPEM directors when a relief request is submitted.
        Deep-links to the eligibility review page.
        
        Args:
            relief_request: The submitted relief request
            recipient_users: List of users to notify (typically ODPEM directors)
            
        Returns:
            List of created Notification objects
        """
        event_name = relief_request.eligible_event.event_name if relief_request.eligible_event else "N/A"
        agency_name = relief_request.agency.agency_name if relief_request.agency else "Unknown"
        tracking_no = f"RR-{relief_request.reliefrqst_id:06d}"
        
        # Deep-link to eligibility review page
        link_url = url_for('eligibility.review_request', request_id=relief_request.reliefrqst_id, _external=False)
        
        notifications = []
        for user in recipient_users:
            notification = NotificationService.create_notification(
                user_id=user.user_id,
                title='New Relief Request Submitted',
                message=f'Agency {agency_name} submitted {tracking_no} for event: {event_name}. Click to review eligibility.',
                notification_type=NotificationService.TYPE_RELIEF_REQUEST_SUBMITTED,
                link_url=link_url,
                reliefrqst_id=relief_request.reliefrqst_id
            )
            notifications.append(notification)
        
        return notifications
    
    @staticmethod
    def create_relief_request_approved_notification(
        relief_request: ReliefRqst,
        recipient_users: List[User],
        approver_name: str
    ) -> List[Notification]:
        """
        Create notifications when a relief request is approved for fulfillment.
        Deep-links to the package preparation page for logistics users,
        and to the request details page for agency users.
        
        Args:
            relief_request: The approved relief request
            recipient_users: List of users to notify
            approver_name: Name of the person who approved the request
            
        Returns:
            List of created Notification objects
        """
        event_name = relief_request.eligible_event.event_name if relief_request.eligible_event else "N/A"
        agency_name = relief_request.agency.agency_name if relief_request.agency else "Unknown"
        tracking_no = f"RR-{relief_request.reliefrqst_id:06d}"
        
        notifications = []
        for user in recipient_users:
            # Different deep-links for different user types based on role
            user_role_codes = [role.code for role in user.roles]
            is_logistics_user = any(code in ['LOGISTICS_OFFICER', 'LOGISTICS_MANAGER'] for code in user_role_codes)
            
            if is_logistics_user:
                # Logistics users: Link to package preparation
                link_url = url_for('packaging.prepare_package', reliefrqst_id=relief_request.reliefrqst_id, _external=False)
                message = f'{tracking_no} from {agency_name} (Event: {event_name}) approved by {approver_name}. Click to prepare fulfillment package.'
            else:
                # Agency users: Link to request details
                link_url = url_for('requests.view_request', request_id=relief_request.reliefrqst_id, _external=False)
                message = f'Your relief request {tracking_no} for {event_name} has been approved by {approver_name}. Click to view details.'
            
            notification = NotificationService.create_notification(
                user_id=user.user_id,
                title='Relief Request Approved',
                message=message,
                notification_type=NotificationService.TYPE_RELIEF_REQUEST_APPROVED,
                link_url=link_url,
                reliefrqst_id=relief_request.reliefrqst_id
            )
            notifications.append(notification)
        
        return notifications
    
    @staticmethod
    def create_relief_request_denied_notification(
        relief_request: ReliefRqst,
        recipient_users: List[User],
        denier_name: str,
        reason: Optional[str] = None
    ) -> List[Notification]:
        """
        Create notifications when a relief request is denied.
        Deep-links to the request details page.
        
        Args:
            relief_request: The denied relief request
            recipient_users: List of users to notify (typically agency users)
            denier_name: Name of the person who denied the request
            reason: Optional reason for denial
            
        Returns:
            List of created Notification objects
        """
        tracking_no = f"RR-{relief_request.reliefrqst_id:06d}"
        link_url = url_for('requests.view_request', request_id=relief_request.reliefrqst_id, _external=False)
        
        message = f'Your relief request {tracking_no} was not approved by {denier_name}.'
        if reason:
            message += f' Reason: {reason}'
        message += ' Click to view details.'
        
        notifications = []
        for user in recipient_users:
            notification = NotificationService.create_notification(
                user_id=user.user_id,
                title='Relief Request Denied',
                message=message,
                notification_type=NotificationService.TYPE_RELIEF_REQUEST_DENIED,
                link_url=link_url,
                reliefrqst_id=relief_request.reliefrqst_id
            )
            notifications.append(notification)
        
        return notifications
    
    @staticmethod
    def create_package_ready_for_approval_notification(
        relief_pkg: ReliefPkg,
        recipient_users: List[User],
        preparer_name: str
    ) -> List[Notification]:
        """
        Create notifications for Logistics Managers when a package is ready for approval.
        Deep-links to the LM approval page with full editing capability.
        
        Args:
            relief_pkg: The relief package ready for review
            recipient_users: List of Logistics Managers to notify
            preparer_name: Name of the Logistics Officer who prepared the package
            
        Returns:
            List of created Notification objects
        """
        relief_request = relief_pkg.relief_request
        tracking_no = f"RR-{relief_request.reliefrqst_id:06d}"
        agency_name = relief_request.agency.agency_name if relief_request.agency else "Unknown"
        
        # Deep-link to LM approval page (with full editing capability and batch drawer)
        link_url = url_for('packaging.approve_package', reliefrqst_id=relief_request.reliefrqst_id, _external=False)
        
        notifications = []
        for user in recipient_users:
            notification = NotificationService.create_notification(
                user_id=user.user_id,
                title='Package Ready for Your Approval',
                message=f'{preparer_name} prepared fulfillment package for {tracking_no} from {agency_name}. Click to review and approve.',
                notification_type=NotificationService.TYPE_PACKAGE_READY_FOR_APPROVAL,
                link_url=link_url,
                reliefrqst_id=relief_request.reliefrqst_id
            )
            notifications.append(notification)
        
        return notifications
    
    @staticmethod
    def create_package_approved_notification(
        relief_pkg: ReliefPkg,
        recipient_users: List[User],
        approver_name: str
    ) -> List[Notification]:
        """
        Create notifications when a package is approved by LM.
        Deep-links to package details or dispatch page for logistics users,
        and to request tracking for agency users.
        
        Args:
            relief_pkg: The approved relief package
            recipient_users: List of users to notify
            approver_name: Name of the Logistics Manager who approved
            
        Returns:
            List of created Notification objects
        """
        relief_request = relief_pkg.relief_request
        tracking_no = f"RR-{relief_request.reliefrqst_id:06d}"
        agency_name = relief_request.agency.agency_name if relief_request.agency else "Unknown"
        
        notifications = []
        for user in recipient_users:
            # Different deep-links for different user types based on role
            user_role_codes = [role.code for role in user.roles]
            is_inventory_clerk = 'INVENTORY_CLERK' in user_role_codes
            is_logistics_user = any(code in ['LOGISTICS_OFFICER', 'LOGISTICS_MANAGER'] for code in user_role_codes)
            
            if is_inventory_clerk:
                # Inventory Clerks: Link to awaiting dispatch page
                link_url = url_for('packaging.awaiting_dispatch', _external=False)
                message = f'Package for {tracking_no} from {agency_name} approved by {approver_name}. Ready to be handed over to agency.'
            elif is_logistics_user:
                # Logistics Officers/Managers: Link to Approved for Dispatch tab
                link_url = url_for('packaging.pending_fulfillment', filter='approved_for_dispatch', _external=False)
                message = f'Package for {tracking_no} from {agency_name} approved by {approver_name}. Ready for dispatch.'
            else:
                # Agency users: Link to request tracking
                link_url = url_for('requests.view_request', request_id=relief_request.reliefrqst_id, _external=False)
                message = f'Your relief request {tracking_no} has been prepared and approved by {approver_name}. Package is ready for dispatch.'
            
            notification = NotificationService.create_notification(
                user_id=user.user_id,
                title='Package Approved',
                message=message,
                notification_type=NotificationService.TYPE_PACKAGE_APPROVED,
                link_url=link_url,
                reliefrqst_id=relief_request.reliefrqst_id
            )
            notifications.append(notification)
        
        return notifications
    
    @staticmethod
    def create_package_dispatched_notification(
        relief_pkg: ReliefPkg,
        recipient_users: List[User],
        dispatcher_name: str
    ) -> List[Notification]:
        """
        Create notifications when a package is dispatched.
        Deep-links to package tracking/details page.
        
        Args:
            relief_pkg: The dispatched relief package
            recipient_users: List of users to notify (agency users, managers)
            dispatcher_name: Name of person who dispatched the package
            
        Returns:
            List of created Notification objects
        """
        relief_request = relief_pkg.relief_request
        tracking_no = f"RR-{relief_request.reliefrqst_id:06d}"
        
        # Deep-link to request details
        link_url = url_for('requests.view_request', request_id=relief_request.reliefrqst_id, _external=False)
        
        notifications = []
        for user in recipient_users:
            notification = NotificationService.create_notification(
                user_id=user.user_id,
                title='Package Dispatched',
                message=f'Relief package for {tracking_no} has been dispatched by {dispatcher_name}. Click to track delivery.',
                notification_type=NotificationService.TYPE_PACKAGE_DISPATCHED,
                link_url=link_url,
                reliefrqst_id=relief_request.reliefrqst_id
            )
            notifications.append(notification)
        
        return notifications
    
    @staticmethod
    def mark_as_read(notification_id: int, user_id: int) -> bool:
        """
        Mark a notification as read.
        Verifies that the notification belongs to the user before marking.
        
        Args:
            notification_id: ID of the notification to mark as read
            user_id: ID of the user (for permission check)
            
        Returns:
            True if successfully marked, False if not found or permission denied
        """
        notification = Notification.query.filter_by(
            id=notification_id,
            user_id=user_id
        ).first()
        
        if not notification:
            return False
        
        notification.status = 'read'
        db.session.commit()
        return True
    
    @staticmethod
    def mark_all_as_read(user_id: int) -> int:
        """
        Mark all notifications as read for a user.
        
        Args:
            user_id: ID of the user
            
        Returns:
            Number of notifications marked as read
        """
        count = Notification.query.filter_by(
            user_id=user_id,
            status='unread'
        ).update({'status': 'read'})
        db.session.commit()
        return count
    
    @staticmethod
    def get_unread_count(user_id: int) -> int:
        """
        Get count of unread notifications for a user.
        
        Args:
            user_id: ID of the user
            
        Returns:
            Number of unread notifications
        """
        return Notification.query.filter_by(
            user_id=user_id,
            status='unread',
            is_archived=False
        ).count()
    
    @staticmethod
    def get_recent_notifications(user_id: int, limit: Optional[int] = None) -> List[Notification]:
        """
        Get recent notifications for a user.
        
        Args:
            user_id: ID of the user
            limit: Maximum number of notifications to return (None = all)
            
        Returns:
            List of Notification objects, newest first
        """
        query = Notification.query.filter_by(
            user_id=user_id,
            is_archived=False
        ).order_by(Notification.created_at.desc())
        
        if limit is not None:
            query = query.limit(limit)
        
        return query.all()
    
    @staticmethod
    def delete_notification(notification_id: int, user_id: int) -> bool:
        """
        Delete a specific notification.
        Verifies that the notification belongs to the user before deleting.
        
        Args:
            notification_id: ID of the notification to delete
            user_id: ID of the user (for permission check)
            
        Returns:
            True if successfully deleted, False if not found or permission denied
        """
        notification = Notification.query.filter_by(
            id=notification_id,
            user_id=user_id
        ).first()
        
        if not notification:
            return False
        
        db.session.delete(notification)
        db.session.commit()
        return True
    
    @staticmethod
    def clear_all_notifications(user_id: int) -> int:
        """
        Delete all notifications for a user.
        
        Args:
            user_id: ID of the user
            
        Returns:
            Number of notifications deleted
        """
        notifications = Notification.query.filter_by(user_id=user_id).all()
        count = len(notifications)
        
        for notification in notifications:
            db.session.delete(notification)
        
        db.session.commit()
        return count
