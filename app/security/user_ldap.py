import re
import random
import string
from flask import current_app
from flask import session
from flask_login import login_user, logout_user
from ldap3 import Connection, Server

from .audit_logger import (log_authentication_event, log_user_management_event,
                           AuditAction, AuditOutcome)
from ..db import db
from ..db.models import User
from ..utils.timezone import now


_user_epoc = 17645000000
# numeric epoch for username randomization


__all__ = ['ldap_login', 'ldap_logout', 'create_ldap_user']

_attribs = ['mail', 'inetUserStatus', 'entryUUID', 'uid']
_cf = None
_logger = None

def _get_conf(key):
    '''Convenient shortcut for fetching config values'''
    # this function fetches values from app.config but localizes the
    # retrieved dictionary in a module variable to speed up access
    global _cf
    if _cf is None:
        app_conf = current_app.config
        _cf = app_conf['LDAP_CONF']
    return _cf[key]

def _log():
    global _logger
    if _logger is None:
        _logger = current_app.logger
    return _logger

def _get_connection(user_dn=None, user_pw=None, can_write=False, auto_bind=True):
    '''
    returns an active connection to the ldap server.
    may not be yet authenticated
    '''
    
    # ToDo Switch to using a server pool housed in the app
    svr = Server(_get_conf('server'), use_ssl=_get_conf('use_ssl'), port=_get_conf('port'))
    _log().debug(f"Connecting to LDAP server {svr}")
    if (can_write or auto_bind) and user_dn is None:
        # obviously it's an admin connection
        admin_dn = _get_conf('admin_dn')
        _log().debug(f'Connecting to LDAP as as admin: {admin_dn}')
        return Connection(svr, admin_dn, _get_conf('admin_pw'),
                          auto_bind=True, read_only=not can_write)
    else:
        # probably the connection we want for user authentication
        return Connection(svr, user_dn, user_pw, auto_bind=False, read_only=True,
                          authentication='SIMPLE')

def _make_user_filter(user_name, search_attr=None):
    '''
    Using the LDAP.user_object_class config setting, construct an
    LDAP filter suitable for searching for the user by email.
    The filter is a basic AND filter for mail and objectClass.
    
    e.g. if user_name == 'fruit@jam.jar', and 
            user_object_class == ['person']
        The resulting filter would be:
            '(&(objectClass=person)(mail=fruit@jam.jar))'
    '''
    if search_attr is None:
        search_attr = _get_conf('user_login_attr')
    _fltr = [f'(objectClass={fc})' for fc in _get_conf('user_object_class')]
    _fltr.append('({}={})'.format(search_attr, user_name))
    return '(&{})'.format(''.join(_fltr))


def _simplify_result(ldap_entry):
    '''
    Since LDAP can have multi-valued attributes, all the entry fields
    come back as a list by default. This strips the list with 1 item
    and just assign the attribute value.
    It also converts all attribute key/names to lowercase
    '''
    _d = ldap_entry.entry_attributes_as_dict
    out = {}
    for key_, val_ in _d.items():
        if isinstance(val_, (list, tuple)) and len(val_) == 1:
            out[key_.lower()] = val_[0]
        else:
            out[key_.lower()] = val_
    return out
        

def ldap_login(user_email, user_pwd):
    '''
    login the user or return false
    '''
    user_filter = _make_user_filter(user_email)
    search_base = _get_conf('user_base_dn')
    user_info = None
    result = None
    with _get_connection() as conn:
        found = conn.search(search_base, user_filter, search_scope='LEVEL',
                            attributes=_attribs)

        result = (False, 'badauth')  # default output. Success changes it
        if len(conn.entries) > 1:
            # 2 users with the same email, none a dem getting in
            # but we need to log that
            # ToDo: Log the multiple user 1-email situation
            _log.error('Multiple users found for email: %s', user_email)
            _log.info('Failing authentication for multiple user with same email: %s', user_email)
            
        elif found and len(conn.entries) == 1:
            entry = conn.entries[0]
            active = 'active' in entry.inetUserStatus
            user_info  = _simplify_result(entry)
            # set user_info so we can tag the bad_auth attempt
            if active:
                _log().debug('Attempting to connect to LDAP as %s', entry.entry_dn)
                with _get_connection(entry.entry_dn, user_pwd, auto_bind=False) as c:
                    if c.bind():
                        _log().info('Success authenticating %s via LDAP',
                                    user_email)
                        result = (True, user_info)
                    else:
                        # bad auth
                        result = (False, 'badauth')
            else:
                result = (False, 'inactive')
                log_authentication_event(
                    action=AuditAction.LOGIN_INACTIVE,
                    email=user_email,
                    outcome=AuditOutcome.DENIED,
                    reason='account_inactive'
                )
    
    if user_info:
        user = User.query.filter_by(email=user_info['mail']).first()
    else:
        user = None


    if result[0]:
        # do the thing to login the user return true
        
        user.last_login_at = now()
        user.failed_login_count = 0
        db.session.commit()    
        login_user(user)
        
        log_authentication_event(
            action=AuditAction.LOGIN_SUCCESS,
            user_id=user.user_id,
            email=user.email,
            outcome=AuditOutcome.SUCCESS
        )
    else:
        # ToDo: Set db user to inactive if LDAP user inactive
        # Does it really matter?
        _log().info(f'Failure authenticating {user_email}. {result[1]}')
        if user and result[1] == 'badauth':
            # count this against the user
            # I don't like this. I think it's better to count it against
            # the client. The user account is innocent
            user.failed_login_count += 1
            db.session.commit()
            log_authentication_event(
                action=AuditAction.LOGIN_FAILURE,
                user_id=user.user_id,
                email=user.email,
                outcome=AuditOutcome.FAILURE,
                reason='invalid_credentials or account inactive'
            )
    return result[0]


def ldap_logout():
    '''Logout user and delete custom session values'''
    # log_authentication_event(
    #     action=AuditAction.LOGOUT,
    #     user_id=user_id,
    #     outcome=AuditOutcome.SUCCESS
    # )
    logout_user()


class DuplicateUserException(Exception):
    """Exception raised for user creation if duplicate email.
    """

    def __init__(self, message=None, *args, **kwargs):
        if message is None:
            self.message = "User exists with same email"
        else:
            self.message = message
        super().__init__(self.message)


def _make_username(user, create_time):
    '''
    Makes a username by:
        - concatenate first name and surname, no space.
        - strip all characters that are not a-z or 0-9
        - take the first 13 characters
        - append the current timestamp, in deciseconds, minus _user_epoc
    _user_epoc is datetime(2025, 11, 30, 5, 53, 20).timestamp() * 10
    '''
    txt_re = re.compile(r'[^a-z0-9]', re.IGNORECASE)
    un_ = ''.join(txt_re.split(''.join([user.first_name, user.last_name])))
    un_ = un_[:13] + '%07d' % ((create_time.timestamp()*10) - _user_epoc, )
    return un_.lower()

def _make_random_password(min_length=14, max_length=24):
    '''Returns a randomly generated password. 
    '''
    pop = string.punctuation +  (string.ascii_letters * 3)
    length = random.randint(min_length, max_length)
    return ''.join(random.sample(pop, length))

def create_ldap_user(new_user, password=None):
    '''
    creates the user in ldap and returns the user_uuid
    or None if user already exist
    '''
    
    create_time = now()
    base_dn = _get_conf('user_base_dn')
    new_user.user_name = _make_username(new_user, create_time)
    dn = f'uid={new_user.user_name},{base_dn}'
    
    user_ = [
        ('objectClass', _get_conf('user_object_class')),
        ('mail', new_user.email),
        ('uid', new_user.user_name),
        ('inetUserStatus', 'active'),
        ('givenName', new_user.first_name),
        ('sn', new_user.last_name),
        ('cn', new_user.full_name),
        ('telephoneNumber', new_user.phone),
        ('employeeType', new_user.job_title),
        ('o', new_user.organization),
    ]

    if password is None:
        # set a random password
        password = _make_random_password()
    user_.append(('userPassword', password))
    
    user_payload = dict([(k,v) for k,v in user_ if v is not None])

    existing_user_filter = _make_user_filter(new_user.email)
    added = False
    with _get_connection(can_write=True, auto_bind=True) as conn:
        found = conn.search(base_dn, existing_user_filter)
        if found:
            error_message = f'A user with email {new_user.email} already exists'
            _log().error('Error creating user: %s', error_message)
            raise DuplicateUserException(error_message)
        added = conn.add(dn, attributes=user_payload)
        if added:
            conn.search(dn, '(objectClass=*)', 'BASE', attributes=['uid', 'mail', 'entryuuid'])
            _log().info('New user created with email %s', new_user.email)
            entry = _simplify_result(conn.entries[0])
            return entry['entryuuid']
