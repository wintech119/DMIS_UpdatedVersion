"""
User Profile Blueprint - Self-Service Profile Management

Allows users to view and edit their own profiles with role-specific
information and features display.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from app.db.models import db, User
from app.core.feature_registry import FeatureRegistry

profile_bp = Blueprint('profile', __name__, url_prefix='/profile')


@profile_bp.route('/')
@login_required
def view_profile():
    """
    View current user's profile with role-specific information.
    Shows user details, assigned roles, features, and permissions.
    """
    # Get user's features and roles
    features = FeatureRegistry.get_accessible_features(current_user)
    primary_role = FeatureRegistry.get_primary_role(current_user)
    role_display_name = FeatureRegistry.get_role_display_name(primary_role) if primary_role else "User"
    
    # Organize features by category
    features_by_category = {}
    for feature in features:
        category = feature.get('category', 'Other')
        if category not in features_by_category:
            features_by_category[category] = []
        features_by_category[category].append(feature)
    
    context = {
        'user': current_user,
        'primary_role': primary_role,
        'role_display_name': role_display_name,
        'features': features,
        'features_by_category': features_by_category,
        'roles': current_user.roles if current_user.roles else []
    }
    
    return render_template('profile/view.html', **context)


@profile_bp.route('/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    """
    Edit current user's profile information.
    Allows updating personal details, notification preferences, etc.
    """
    if request.method == 'POST':
        try:
            # Get form data
            first_name = request.form.get('first_name', '').strip()
            last_name = request.form.get('last_name', '').strip()
            phone = request.form.get('phone', '').strip()
            job_title = request.form.get('job_title', '').strip()
            timezone = request.form.get('timezone', 'America/Jamaica')
            language = request.form.get('language', 'en')
            
            # Validate required fields
            if not first_name or not last_name:
                flash('First name and last name are required.', 'danger')
                return redirect(url_for('profile.edit_profile'))
            
            # Update user
            current_user.first_name = first_name.upper()
            current_user.last_name = last_name.upper()
            current_user.full_name = f"{first_name.upper()} {last_name.upper()}"
            current_user.phone = phone
            current_user.job_title = job_title
            current_user.timezone = timezone
            current_user.language = language
            
            db.session.commit()
            
            flash('Profile updated successfully!', 'success')
            return redirect(url_for('profile.view_profile'))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Error updating profile')
            flash('An error occurred while updating your profile. Please try again.', 'danger')
            return redirect(url_for('profile.edit_profile'))
    
    # GET request - show edit form
    timezones = [
        'America/Jamaica',
        'America/New_York',
        'America/Los_Angeles',
        'America/Chicago',
        'Europe/London',
        'UTC'
    ]
    
    languages = [
        ('en', 'English'),
        ('es', 'Spanish (Español)'),
        ('fr', 'French (Français)')
    ]
    
    context = {
        'user': current_user,
        'timezones': timezones,
        'languages': languages
    }
    
    return render_template('profile/edit.html', **context)


@profile_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """
    Change user's password with current password verification.
    """
    if request.method == 'POST':
        try:
            current_password = request.form.get('current_password', '')
            new_password = request.form.get('new_password', '')
            confirm_password = request.form.get('confirm_password', '')
            
            # Validate current password
            if not check_password_hash(current_user.password_hash, current_password):
                flash('Current password is incorrect.', 'danger')
                return redirect(url_for('profile.change_password'))
            
            # Validate new password
            if len(new_password) < 8:
                flash('New password must be at least 8 characters long.', 'danger')
                return redirect(url_for('profile.change_password'))
            
            if new_password != confirm_password:
                flash('New passwords do not match.', 'danger')
                return redirect(url_for('profile.change_password'))
            
            # Update password
            current_user.password_hash = generate_password_hash(new_password)
            current_user.password_changed_at = db.func.now()
            
            db.session.commit()
            
            flash('Password changed successfully!', 'success')
            return redirect(url_for('profile.view_profile'))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Error changing password')
            flash('An error occurred while changing your password. Please try again.', 'danger')
            return redirect(url_for('profile.change_password'))
    
    # GET request - show change password form
    context = {
        'user': current_user
    }
    
    return render_template('profile/change_password.html', **context)


@profile_bp.route('/preferences', methods=['GET', 'POST'])
@login_required
def preferences():
    """
    Manage user notification and display preferences.
    """
    if request.method == 'POST':
        try:
            # Get notification preferences
            email_notifications = request.form.get('email_notifications') == 'on'
            sms_notifications = request.form.get('sms_notifications') == 'on'
            push_notifications = request.form.get('push_notifications') == 'on'
            
            # Build preferences JSON
            import json
            prefs = {
                'email': email_notifications,
                'sms': sms_notifications,
                'push': push_notifications
            }
            
            current_user.notification_preferences = json.dumps(prefs)
            
            db.session.commit()
            
            flash('Preferences updated successfully!', 'success')
            return redirect(url_for('profile.view_profile'))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Error updating preferences')
            flash('An error occurred while updating your preferences. Please try again.', 'danger')
            return redirect(url_for('profile.preferences'))
    
    # GET request - show preferences form
    import json
    prefs = {}
    if current_user.notification_preferences:
        try:
            prefs = json.loads(current_user.notification_preferences)
        except:
            prefs = {}
    
    context = {
        'user': current_user,
        'preferences': prefs
    }
    
    return render_template('profile/preferences.html', **context)
