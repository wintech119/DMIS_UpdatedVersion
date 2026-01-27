from flask import Blueprint, render_template, jsonify, request, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import func
from app.db.models import db, Inventory, Item, Notification
from app.services.notification_service import NotificationService
from app.security.url_safety import validate_internal_url
from app.security.rate_limiting import limit_api, limit_bulk

notifications_bp = Blueprint('notifications', __name__)

@notifications_bp.route('/api/unread_count')
@login_required
def unread_count():
    """Get count of unread notifications for current user"""
    unread_count = NotificationService.get_unread_count(current_user.user_id)
    return jsonify({'count': unread_count})

@notifications_bp.route('/api/list')
@login_required
def notification_list():
    """Get notifications as JSON for offcanvas panel"""
    notifications = NotificationService.get_recent_notifications(current_user.user_id, limit=10)
    
    def get_safe_link(link_url):
        """Return validated internal URL or default to notifications index"""
        if link_url and validate_internal_url(link_url):
            return link_url
        return url_for('notifications.index')
    
    return jsonify({
        'notifications': [{
            'id': n.id,
            'title': n.title,
            'message': n.message,
            'type': n.type,
            'status': n.status,
            'link_url': get_safe_link(n.link_url),
            'created_at': n.created_at.strftime('%b %d, %Y at %I:%M %p') if n.created_at else 'Just now',
            'is_unread': n.status == 'unread'
        } for n in notifications]
    })

@notifications_bp.route('/')
@login_required
def index():
    """Display all notifications for current user"""
    from datetime import timedelta
    from app.utils.timezone import now, get_date_only
    
    # Get actual notifications from database (no limit - show all)
    user_notifications = NotificationService.get_recent_notifications(current_user.user_id, limit=None)
    
    # Also get low stock items (legacy feature)
    low_stock_items = db.session.query(
        Item.item_id, 
        Item.item_name,
        func.sum(Inventory.usable_qty).label('total_qty'),
        Item.reorder_qty
    ).join(Inventory).filter(
        Item.status_code == 'A'
    ).group_by(
        Item.item_id, Item.item_name, Item.reorder_qty
    ).having(
        func.sum(Inventory.usable_qty) <= Item.reorder_qty
    ).all()
    
    # Calculate datetime boundaries for filtering
    today_start = get_date_only()
    week_start = today_start - timedelta(days=today_start.weekday())
    
    # Precompute notification counts for metrics
    unread_count = sum(1 for n in user_notifications if n.status == 'unread')
    read_count = sum(1 for n in user_notifications if n.status == 'read')
    today_count = sum(1 for n in user_notifications if n.created_at and n.created_at >= today_start)
    week_count = sum(1 for n in user_notifications if n.created_at and n.created_at >= week_start)
    
    return render_template('notifications/index.html', 
                         notifications=user_notifications,
                         low_stock_items=low_stock_items,
                         today=today_start,
                         this_week=week_start,
                         unread_count=unread_count,
                         read_count=read_count,
                         today_count=today_count,
                         week_count=week_count)

@notifications_bp.route('/<int:notification_id>/mark-read', methods=['POST'])
@login_required
def mark_read(notification_id):
    """Mark a notification as read and redirect to its link"""
    notification = Notification.query.get_or_404(notification_id)
    
    # Verify user owns this notification
    if notification.user_id != current_user.user_id:
        return redirect(url_for('notifications.index')), 403
    
    # Mark as read
    NotificationService.mark_as_read(notification_id, current_user.user_id)
    
    # Redirect to the notification's link if it exists and is safe
    # Defense-in-depth: validate stored URLs before redirecting
    if notification.link_url and validate_internal_url(notification.link_url):
        return redirect(notification.link_url)
    else:
        return redirect(url_for('notifications.index'))

@notifications_bp.route('/<int:notification_id>/delete', methods=['POST'])
@login_required
def delete_notification(notification_id):
    """Delete a specific notification"""
    from flask import flash
    
    success = NotificationService.delete_notification(notification_id, current_user.user_id)
    
    if success:
        flash('Notification deleted successfully.', 'success')
    else:
        flash('Notification not found or access denied.', 'danger')
    
    return redirect(url_for('notifications.index'))

@notifications_bp.route('/clear-all', methods=['POST'])
@login_required
@limit_bulk
def clear_all():
    """Delete all notifications for the current user"""
    from flask import flash
    
    count = NotificationService.clear_all_notifications(current_user.user_id)
    
    # Return JSON for AJAX requests, redirect for form submissions
    if request.is_json or request.headers.get('Accept') == 'application/json':
        return jsonify({'success': True, 'count': count, 'message': f'Cleared {count} notification{"s" if count != 1 else ""}'}), 200
    
    if count > 0:
        flash(f'Successfully cleared {count} notification{"s" if count != 1 else ""}.', 'success')
    else:
        flash('No notifications to clear.', 'info')
    
    return redirect(url_for('notifications.index'))

@notifications_bp.route('/api/clear-all', methods=['POST'])
@login_required
@limit_bulk
def api_clear_all():
    """JSON API: Delete all notifications for the current user"""
    count = NotificationService.clear_all_notifications(current_user.user_id)
    return jsonify({'success': True, 'count': count, 'message': f'Cleared {count} notification{"s" if count != 1 else ""}'}), 200

@notifications_bp.route('/api/delete/<int:notification_id>', methods=['POST'])
@login_required
@limit_api
def api_delete_notification(notification_id):
    """JSON API: Delete a specific notification"""
    success = NotificationService.delete_notification(notification_id, current_user.user_id)
    
    if success:
        return jsonify({'success': True, 'message': 'Notification deleted successfully'}), 200
    else:
        return jsonify({'success': False, 'message': 'Notification not found or access denied'}), 404

@notifications_bp.route('/api/mark-read/<int:notification_id>', methods=['POST'])
@login_required
@limit_api
def api_mark_read(notification_id):
    """JSON API: Mark a single notification as read"""
    success = NotificationService.mark_as_read(notification_id, current_user.user_id)
    
    if success:
        return jsonify({'success': True, 'message': 'Notification marked as read'}), 200
    else:
        return jsonify({'success': False, 'message': 'Notification not found or access denied'}), 404
