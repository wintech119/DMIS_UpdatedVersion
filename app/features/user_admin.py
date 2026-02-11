from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from app.db.models import db, User, Role, UserRole, UserWarehouse, Warehouse, Agency, Custodian
from app.core.rbac import role_required
from app.security.audit_logger import (
    log_user_management_event, log_data_event,
    AuditAction, AuditOutcome
)
from ..security.user_keycloak import create_keycloak_user, DuplicateUserException as KCDuplicate
from ..security.user_ldap import create_ldap_user, DuplicateUserException as LDAPDuplicate

user_admin_bp = Blueprint('user_admin', __name__)

def get_assignable_roles(user):
    """
    Get roles that the current user is allowed to assign to other users.
    
    - SYSTEM_ADMINISTRATOR: Can assign ANY role (full privileges)
    - CUSTODIAN: Can assign operational roles only (excludes admin roles)
    
    Returns:
        List of Role objects the user can assign
    """
    user_role_codes = [role.code for role in user.roles]
    
    # System administrators can assign any role
    if 'SYSTEM_ADMINISTRATOR' in user_role_codes or 'SYS_ADMIN' in user_role_codes:
        return Role.query.all()
    
    # Custodians can assign operational roles only (no admin elevation)
    if 'CUSTODIAN' in user_role_codes:
        restricted_roles = ['SYSTEM_ADMINISTRATOR', 'SYS_ADMIN']
        return Role.query.filter(~Role.code.in_(restricted_roles)).all()
    
    # Default: no role assignment privileges
    return []

def validate_role_assignment(user, role_ids):
    """
    Validate that the current user has permission to assign the specified roles.
    
    Args:
        user: Current user attempting to assign roles
        role_ids: List of role IDs being assigned
        
    Returns:
        tuple: (is_valid: bool, error_message: str or None)
    """
    if not role_ids:
        return True, None
    
    assignable_roles = get_assignable_roles(user)
    assignable_role_ids = {role.id for role in assignable_roles}
    
    attempted_role_ids = set(role_ids)
    
    # Check if user is trying to assign roles they don't have permission for
    unauthorized_ids = attempted_role_ids - assignable_role_ids
    
    if unauthorized_ids:
        unauthorized_roles = Role.query.filter(Role.id.in_(unauthorized_ids)).all()
        role_names = ', '.join([r.name for r in unauthorized_roles])
        return False, f'You do not have permission to assign the following roles: {role_names}'
    
    return True, None

@user_admin_bp.route('/')
@login_required
@role_required('SYSTEM_ADMINISTRATOR', 'SYS_ADMIN', 'CUSTODIAN')
def index():
    users = User.query.order_by(User.create_dtime.desc()).all()
    
    total_users = len(users)
    active_users = sum(1 for u in users if u.is_active)
    inactive_users = sum(1 for u in users if not u.is_active)
    locked_users = sum(1 for u in users if u.is_locked)
    
    mfa_enabled_users = sum(1 for u in users if u.mfa_enabled)
    mfa_percentage = round((mfa_enabled_users / total_users * 100) if total_users > 0 else 0, 1)
    
    admin_role_codes = ['SYSTEM_ADMINISTRATOR', 'SYS_ADMIN']
    admin_users = sum(1 for u in users if any(r.code in admin_role_codes for r in u.roles))
    
    metrics = {
        'total_users': total_users,
        'active_users': active_users,
        'inactive_users': inactive_users,
        'locked_users': locked_users,
        'mfa_enabled': mfa_enabled_users,
        'mfa_percentage': mfa_percentage,
        'admin_users': admin_users
    }
    
    return render_template('user_admin/index.html', users=users, metrics=metrics)

def create_backend_user(user_object, password=None):
    '''
    Calls the appropriate backend for user creation based on config
    '''
    _user_auth_mode = current_app.config.get('USER_AUTH_MODE', 'ldap')
    if _user_auth_mode == 'ldap':
        return create_ldap_user(user_object, password=password)
    else:
        return create_keycloak_user(user_object, password=password)


@user_admin_bp.route('/create', methods=['GET', 'POST'])
@login_required
@role_required('SYSTEM_ADMINISTRATOR', 'SYS_ADMIN', 'CUSTODIAN')
def create():
    form_valid = True
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        user_name = request.form.get('user_name', '').strip().upper()[:20]
        password = request.form.get('password', '')
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        organization_value = request.form.get('organization', '').strip()
        job_title = request.form.get('job_title', '').strip()
        phone = request.form.get('phone', '').strip()
        is_active = request.form.get('is_active') == 'on'
        
        if not email or not password or not user_name:
            flash('Email, user name, and password are required.', 'danger')
            form_valid = False
        if form_valid and User.query.filter_by(email=email).count() > 1:
            flash('A user with this email already exists.', 'danger')
            form_valid = False
        
        organization_name = None
        agency_id = None
        
        if form_valid and organization_value:
            if ':' in organization_value:
                org_type, org_id = organization_value.split(':', 1)

                if org_type not in ['AGENCY', 'CUSTODIAN']:
                    flash('Invalid organization type. Must be AGENCY or CUSTODIAN.', 'danger')
                    form_valid = False
                
                if form_valid and  not org_id.isdigit():
                    flash('Invalid organization ID format.', 'danger')
                    form_valid = False
                
                if form_valid and org_type == 'AGENCY':
                    agency = Agency.query.filter_by(agency_id=int(org_id), status_code='A').first()
                    if agency:
                        organization_name = agency.agency_name
                        agency_id = agency.agency_id
                    else:
                        flash('Invalid agency selected.', 'danger')
                        form_valid = False
                
                elif form_valid: # i.e. not org_type == AGENCY
                    custodian = Custodian.query.filter_by(custodian_id=int(org_id)).first()
                    if custodian:
                        organization_name = custodian.custodian_name
                        agency_id = None
                    else:
                        flash('Invalid custodian selected.', 'danger')
                        form_valid = False            
            else:
                flash('Invalid organization format. Please select from the dropdown.', 'danger')
                form_valid = False

        role_ids = request.form.getlist('roles')
        if form_valid and role_ids:
            role_ids = map(int, role_ids)
            is_valid, error_msg = validate_role_assignment(current_user, role_ids)
            if not is_valid:
                flash(error_msg, 'danger')
                form_valid = False

        if form_valid:
            full_name = f"{first_name.strip()} {last_name.strip()}".strip()
            
            try:
                new_user = User(
                    email=email,
                    user_name=user_name,
                    # password_hash=generate_password_hash(password),
                    first_name=first_name,
                    last_name=last_name,
                    full_name=full_name if full_name else None,
                    organization=organization_name,
                    agency_id=agency_id,
                    job_title=job_title if job_title else None,
                    phone=phone if phone else None,
                    is_active=is_active
                )
                kc_user_uuid = create_backend_user(new_user, password=password)
                new_user.user_uuid = kc_user_uuid
                new_user.password_hash = 'x'  # invalid hash, use LDAP
                
                db.session.add(new_user)
                db.session.flush()
                
                for role_id in role_ids:
                    user_role = UserRole(user_id=new_user.user_id, role_id=int(role_id))
                    db.session.add(user_role)
                
                warehouse_ids = request.form.getlist('warehouses')
                for warehouse_id in warehouse_ids:
                    user_warehouse = UserWarehouse(user_id=new_user.user_id, warehouse_id=int(warehouse_id))
                    db.session.add(user_warehouse)
                
                db.session.commit()
                log_user_management_event(
                    action=AuditAction.USER_CREATE,
                    actor_id=current_user.user_id,
                    target_user_id=new_user.user_id,
                    details={
                        'email': email,
                        'roles': role_ids,
                        'is_active': is_active
                    },
                    outcome=AuditOutcome.SUCCESS
                )
                flash(f'User {email} created successfully.', 'success')
                return redirect(url_for('user_admin.index'))
            except (KCDuplicate, LDAPDuplicate) as e:
                flash('A user with this email already exists.', 'danger')
                form_valid = False
                log_user_management_event(
                    action=AuditAction.USER_CREATE,
                    actor_id=current_user.user_id,
                    target_user_id=0,
                    details={'email': email, 'error': type(e).__name__},
                    outcome=AuditOutcome.ERROR
                )
            except ValueError as e:
                flash('Invalid email format for backend user provisioning.', 'danger')
                form_valid = False
                log_user_management_event(
                    action=AuditAction.USER_CREATE,
                    actor_id=current_user.user_id,
                    target_user_id=0,
                    details={'email': email, 'error': type(e).__name__},
                    outcome=AuditOutcome.ERROR
                )
            # except Exception as e:
            #     db.session.rollback()
            #     flash(f'Error creating user: {str(e)}', 'danger')
            #     form_valid = False
    
    roles = get_assignable_roles(current_user)
    warehouses = Warehouse.query.filter_by(status_code='A').all()
    agencies = Agency.query.filter_by(status_code='A').order_by(Agency.agency_name).all()
    custodians = Custodian.query.order_by(Custodian.custodian_name).all()
    
    return render_template('user_admin/create.html',
                         roles=roles,
                         warehouses=warehouses,
                         agencies=agencies,
                         custodians=custodians)

@user_admin_bp.route('/<int:user_id>')
@login_required
@role_required('SYSTEM_ADMINISTRATOR', 'SYS_ADMIN', 'CUSTODIAN')
def view(user_id):
    
    user = User.query.get_or_404(user_id)
    return render_template('user_admin/view.html', user=user)

@user_admin_bp.route('/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('SYSTEM_ADMINISTRATOR', 'SYS_ADMIN', 'CUSTODIAN')
def edit(user_id):
    
    user = User.query.get_or_404(user_id)
    
    if request.method == 'POST':
        if 'organization' not in request.form:
            flash('Organization field is required.', 'danger')
            agencies = Agency.query.filter_by(status_code='A').order_by(Agency.agency_name).all()
            custodians = Custodian.query.order_by(Custodian.custodian_name).all()
            roles = get_assignable_roles(current_user)
            warehouses = Warehouse.query.filter_by(status_code='A').all()
            user_role_ids = [r.id for r in user.roles]
            user_warehouse_ids = [w.warehouse_id for w in user.warehouses]
            current_org_value = ''
            if user.agency_id:
                current_org_value = f'AGENCY:{user.agency_id}'
            elif user.organization:
                custodian = Custodian.query.filter_by(custodian_name=user.organization).first()
                if custodian:
                    current_org_value = f'CUSTODIAN:{custodian.custodian_id}'
            return render_template('user_admin/edit.html',
                                 user=user,
                                 roles=roles,
                                 warehouses=warehouses,
                                 agencies=agencies,
                                 custodians=custodians,
                                 user_role_ids=user_role_ids,
                                 user_warehouse_ids=user_warehouse_ids,
                                 current_org_value=current_org_value)
        
        user_name = request.form.get('user_name', '').strip().upper()[:20]
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        organization_value = request.form.get('organization', '').strip()
        job_title = request.form.get('job_title', '').strip() or None
        phone = request.form.get('phone', '').strip() or None
        is_active = request.form.get('is_active') == 'on'
        password = request.form.get('password', '').strip()
        
        if not user_name:
            flash('User name is required.', 'danger')
            agencies = Agency.query.filter_by(status_code='A').order_by(Agency.agency_name).all()
            custodians = Custodian.query.order_by(Custodian.custodian_name).all()
            roles = get_assignable_roles(current_user)
            warehouses = Warehouse.query.filter_by(status_code='A').all()
            user_role_ids = [r.id for r in user.roles]
            user_warehouse_ids = [w.warehouse_id for w in user.warehouses]
            current_org_value = ''
            if user.agency_id:
                current_org_value = f'AGENCY:{user.agency_id}'
            elif user.organization:
                custodian = Custodian.query.filter_by(custodian_name=user.organization).first()
                if custodian:
                    current_org_value = f'CUSTODIAN:{custodian.custodian_id}'
            return render_template('user_admin/edit.html',
                                 user=user,
                                 roles=roles,
                                 warehouses=warehouses,
                                 agencies=agencies,
                                 custodians=custodians,
                                 user_role_ids=user_role_ids,
                                 user_warehouse_ids=user_warehouse_ids,
                                 current_org_value=current_org_value)
        
        organization_name = None
        agency_id = None
        
        if organization_value:
            if ':' not in organization_value:
                flash('Invalid organization format. Please select from the dropdown.', 'danger')
                agencies = Agency.query.filter_by(status_code='A').order_by(Agency.agency_name).all()
                custodians = Custodian.query.order_by(Custodian.custodian_name).all()
                roles = get_assignable_roles(current_user)
                warehouses = Warehouse.query.filter_by(status_code='A').all()
                user_role_ids = [r.id for r in user.roles]
                user_warehouse_ids = [w.warehouse_id for w in user.warehouses]
                current_org_value = ''
                if user.agency_id:
                    current_org_value = f'AGENCY:{user.agency_id}'
                elif user.organization:
                    custodian = Custodian.query.filter_by(custodian_name=user.organization).first()
                    if custodian:
                        current_org_value = f'CUSTODIAN:{custodian.custodian_id}'
                return render_template('user_admin/edit.html',
                                     user=user,
                                     roles=roles,
                                     warehouses=warehouses,
                                     agencies=agencies,
                                     custodians=custodians,
                                     user_role_ids=user_role_ids,
                                     user_warehouse_ids=user_warehouse_ids,
                                     current_org_value=current_org_value)
            
            org_type, org_id = organization_value.split(':', 1)
            
            if org_type not in ['AGENCY', 'CUSTODIAN']:
                flash('Invalid organization type. Must be AGENCY or CUSTODIAN.', 'danger')
                agencies = Agency.query.filter_by(status_code='A').order_by(Agency.agency_name).all()
                custodians = Custodian.query.order_by(Custodian.custodian_name).all()
                roles = get_assignable_roles(current_user)
                warehouses = Warehouse.query.filter_by(status_code='A').all()
                user_role_ids = [r.id for r in user.roles]
                user_warehouse_ids = [w.warehouse_id for w in user.warehouses]
                current_org_value = ''
                if user.agency_id:
                    current_org_value = f'AGENCY:{user.agency_id}'
                elif user.organization:
                    custodian = Custodian.query.filter_by(custodian_name=user.organization).first()
                    if custodian:
                        current_org_value = f'CUSTODIAN:{custodian.custodian_id}'
                return render_template('user_admin/edit.html',
                                     user=user,
                                     roles=roles,
                                     warehouses=warehouses,
                                     agencies=agencies,
                                     custodians=custodians,
                                     user_role_ids=user_role_ids,
                                     user_warehouse_ids=user_warehouse_ids,
                                     current_org_value=current_org_value)
            
            if not org_id.isdigit():
                flash('Invalid organization ID format.', 'danger')
                agencies = Agency.query.filter_by(status_code='A').order_by(Agency.agency_name).all()
                custodians = Custodian.query.order_by(Custodian.custodian_name).all()
                roles = get_assignable_roles(current_user)
                warehouses = Warehouse.query.filter_by(status_code='A').all()
                user_role_ids = [r.id for r in user.roles]
                user_warehouse_ids = [w.warehouse_id for w in user.warehouses]
                current_org_value = ''
                if user.agency_id:
                    current_org_value = f'AGENCY:{user.agency_id}'
                elif user.organization:
                    custodian = Custodian.query.filter_by(custodian_name=user.organization).first()
                    if custodian:
                        current_org_value = f'CUSTODIAN:{custodian.custodian_id}'
                return render_template('user_admin/edit.html',
                                     user=user,
                                     roles=roles,
                                     warehouses=warehouses,
                                     agencies=agencies,
                                     custodians=custodians,
                                     user_role_ids=user_role_ids,
                                     user_warehouse_ids=user_warehouse_ids,
                                     current_org_value=current_org_value)
            
            if org_type == 'AGENCY':
                agency = Agency.query.filter_by(agency_id=int(org_id), status_code='A').first()
                if agency:
                    organization_name = agency.agency_name
                    agency_id = agency.agency_id
                else:
                    flash('Invalid agency selected.', 'danger')
                    agencies = Agency.query.filter_by(status_code='A').order_by(Agency.agency_name).all()
                    custodians = Custodian.query.order_by(Custodian.custodian_name).all()
                    roles = get_assignable_roles(current_user)
                    warehouses = Warehouse.query.filter_by(status_code='A').all()
                    user_role_ids = [r.id for r in user.roles]
                    user_warehouse_ids = [w.warehouse_id for w in user.warehouses]
                    current_org_value = ''
                    if user.agency_id:
                        current_org_value = f'AGENCY:{user.agency_id}'
                    elif user.organization:
                        custodian = Custodian.query.filter_by(custodian_name=user.organization).first()
                        if custodian:
                            current_org_value = f'CUSTODIAN:{custodian.custodian_id}'
                    return render_template('user_admin/edit.html',
                                         user=user,
                                         roles=roles,
                                         warehouses=warehouses,
                                         agencies=agencies,
                                         custodians=custodians,
                                         user_role_ids=user_role_ids,
                                         user_warehouse_ids=user_warehouse_ids,
                                         current_org_value=current_org_value)
            
            else:
                custodian = Custodian.query.filter_by(custodian_id=int(org_id)).first()
                if custodian:
                    organization_name = custodian.custodian_name
                    agency_id = None
                else:
                    flash('Invalid custodian selected.', 'danger')
                    agencies = Agency.query.filter_by(status_code='A').order_by(Agency.agency_name).all()
                    custodians = Custodian.query.order_by(Custodian.custodian_name).all()
                    roles = get_assignable_roles(current_user)
                    warehouses = Warehouse.query.filter_by(status_code='A').all()
                    user_role_ids = [r.id for r in user.roles]
                    user_warehouse_ids = [w.warehouse_id for w in user.warehouses]
                    current_org_value = ''
                    if user.agency_id:
                        current_org_value = f'AGENCY:{user.agency_id}'
                    elif user.organization:
                        custodian = Custodian.query.filter_by(custodian_name=user.organization).first()
                        if custodian:
                            current_org_value = f'CUSTODIAN:{custodian.custodian_id}'
                    return render_template('user_admin/edit.html',
                                         user=user,
                                         roles=roles,
                                         warehouses=warehouses,
                                         agencies=agencies,
                                         custodians=custodians,
                                         user_role_ids=user_role_ids,
                                         user_warehouse_ids=user_warehouse_ids,
                                         current_org_value=current_org_value)
        
        try:
            user.user_name = user_name
            user.first_name = first_name
            user.last_name = last_name
            user.organization = organization_name
            user.agency_id = agency_id
            user.job_title = job_title
            user.phone = phone
            user.is_active = is_active
            
            full_name = f"{first_name} {last_name}".strip()
            user.full_name = full_name if full_name else None
            
            if password:
                user.password_hash = generate_password_hash(password)
            
            UserRole.query.filter_by(user_id=user.user_id).delete()
            role_ids = request.form.getlist('roles')
            if role_ids:
                role_ids_int = [int(r) for r in role_ids]
                is_valid, error_msg = validate_role_assignment(current_user, role_ids_int)
                if not is_valid:
                    db.session.rollback()
                    flash(error_msg, 'danger')
                    agencies = Agency.query.filter_by(status_code='A').order_by(Agency.agency_name).all()
                    custodians = Custodian.query.order_by(Custodian.custodian_name).all()
                    roles = get_assignable_roles(current_user)
                    warehouses = Warehouse.query.filter_by(status_code='A').all()
                    user_role_ids = [r.id for r in user.roles]
                    user_warehouse_ids = [w.warehouse_id for w in user.warehouses]
                    current_org_value = ''
                    if user.agency_id:
                        current_org_value = f'AGENCY:{user.agency_id}'
                    elif user.organization:
                        custodian = Custodian.query.filter_by(custodian_name=user.organization).first()
                        if custodian:
                            current_org_value = f'CUSTODIAN:{custodian.custodian_id}'
                    return render_template('user_admin/edit.html',
                                         user=user,
                                         roles=roles,
                                         warehouses=warehouses,
                                         agencies=agencies,
                                         custodians=custodians,
                                         user_role_ids=user_role_ids,
                                         user_warehouse_ids=user_warehouse_ids,
                                         current_org_value=current_org_value)
            
            for role_id in role_ids:
                user_role = UserRole(user_id=user.user_id, role_id=int(role_id))
                db.session.add(user_role)
            
            UserWarehouse.query.filter_by(user_id=user.user_id).delete()
            warehouse_ids = request.form.getlist('warehouses')
            for warehouse_id in warehouse_ids:
                user_warehouse = UserWarehouse(user_id=user.user_id, warehouse_id=int(warehouse_id))
                db.session.add(user_warehouse)
            
            db.session.commit()
            
            log_user_management_event(
                action=AuditAction.USER_UPDATE,
                actor_id=current_user.user_id,
                target_user_id=user.user_id,
                details={
                    'roles_changed': bool(role_ids),
                    'is_active': user.is_active
                },
                outcome=AuditOutcome.SUCCESS
            )
            
            flash(f'User {user.email} updated successfully.', 'success')
            return redirect(url_for('user_admin.view', user_id=user.user_id))
        
        except Exception as e:
            db.session.rollback()
            db.session.refresh(user)
            current_app.logger.exception('Error updating user')
            
            log_user_management_event(
                action=AuditAction.USER_UPDATE,
                actor_id=current_user.user_id,
                target_user_id=user.user_id,
                details={'error': type(e).__name__},
                outcome=AuditOutcome.ERROR
            )
            
            flash('An error occurred while updating the user. Please try again or contact support.', 'danger')
            agencies = Agency.query.filter_by(status_code='A').order_by(Agency.agency_name).all()
            custodians = Custodian.query.order_by(Custodian.custodian_name).all()
            roles = get_assignable_roles(current_user)
            warehouses = Warehouse.query.filter_by(status_code='A').all()
            user_role_ids = [r.id for r in user.roles]
            user_warehouse_ids = [w.warehouse_id for w in user.warehouses]
            current_org_value = ''
            if user.agency_id:
                current_org_value = f'AGENCY:{user.agency_id}'
            elif user.organization:
                custodian = Custodian.query.filter_by(custodian_name=user.organization).first()
                if custodian:
                    current_org_value = f'CUSTODIAN:{custodian.custodian_id}'
            return render_template('user_admin/edit.html',
                                 user=user,
                                 roles=roles,
                                 warehouses=warehouses,
                                 agencies=agencies,
                                 custodians=custodians,
                                 user_role_ids=user_role_ids,
                                 user_warehouse_ids=user_warehouse_ids,
                                 current_org_value=current_org_value)
    
    roles = get_assignable_roles(current_user)
    warehouses = Warehouse.query.filter_by(status_code='A').all()
    agencies = Agency.query.filter_by(status_code='A').order_by(Agency.agency_name).all()
    custodians = Custodian.query.order_by(Custodian.custodian_name).all()
    user_role_ids = [r.id for r in user.roles]
    user_warehouse_ids = [w.warehouse_id for w in user.warehouses]
    
    current_org_value = ''
    if user.agency_id:
        current_org_value = f'AGENCY:{user.agency_id}'
    elif user.organization:
        custodian = Custodian.query.filter_by(custodian_name=user.organization).first()
        if custodian:
            current_org_value = f'CUSTODIAN:{custodian.custodian_id}'
    
    return render_template('user_admin/edit.html', 
                         user=user, 
                         roles=roles, 
                         warehouses=warehouses,
                         agencies=agencies,
                         custodians=custodians,
                         user_role_ids=user_role_ids,
                         user_warehouse_ids=user_warehouse_ids,
                         current_org_value=current_org_value)

@user_admin_bp.route('/<int:user_id>/deactivate', methods=['POST'])
@login_required
@role_required('SYSTEM_ADMINISTRATOR', 'SYS_ADMIN', 'CUSTODIAN')
def deactivate(user_id):
    
    if user_id == current_user.user_id:
        flash('You cannot deactivate your own account.', 'danger')
        return redirect(url_for('user_admin.view', user_id=user_id))
    
    user = User.query.get_or_404(user_id)
    user.is_active = False
    db.session.commit()
    
    flash(f'User {user.email} has been deactivated.', 'success')
    return redirect(url_for('user_admin.index'))

@user_admin_bp.route('/<int:user_id>/activate', methods=['POST'])
@login_required
@role_required('SYSTEM_ADMINISTRATOR', 'SYS_ADMIN', 'CUSTODIAN')
def activate(user_id):
    
    user = User.query.get_or_404(user_id)
    user.is_active = True
    db.session.commit()
    
    flash(f'User {user.email} has been activated.', 'success')
    return redirect(url_for('user_admin.index'))
