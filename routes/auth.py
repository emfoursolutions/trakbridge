"""
ABOUTME: Authentication routes for login, logout, and SSO callback handling
ABOUTME: Provides web interface for multi-provider authentication in TrakBridge

File: routes/auth.py

Description:
    Authentication routes blueprint providing web interface for user authentication
    in TrakBridge. Handles login/logout flows for all authentication providers (Local,
    LDAP, OIDC), OIDC callback processing, session management, and user profile
    functionality. Integrates with the authentication manager for seamless
    multi-provider authentication experience.

Key features:
    - Universal login page with provider selection
    - Local username/password authentication
    - OIDC SSO authentication with redirect handling
    - LDAP authentication integration
    - Secure logout with session invalidation
    - User profile management and password changes
    - Admin user management interface
    - Session security and CSRF protection
    - Comprehensive error handling and user feedback

Author: Emfour Solutions
Created: 2025-07-26
Last Modified: 2025-07-26
Version: 1.0.0
"""

# Standard library imports
import logging
from datetime import datetime

# Third-party imports
from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session,
    jsonify, current_app, g
)

# Local application imports
from models.user import User, UserRole, AuthProvider
from services.auth import (
    AuthenticationManager, LocalAuthProvider, LDAPAuthProvider, OIDCAuthProvider,
    get_current_user, logout_user, require_auth, admin_required
)


# Module-level logger
logger = logging.getLogger(__name__)

# Create blueprint
bp = Blueprint('auth', __name__, url_prefix='/auth')


def get_auth_manager() -> AuthenticationManager:
    """Get authentication manager from app context"""
    return getattr(current_app, 'auth_manager', None)


@bp.route('/login', methods=['GET', 'POST'])
def login():
    """
    Universal login page supporting all authentication providers
    """
    # Check if already authenticated
    if get_current_user():
        next_url = session.pop('next_url', url_for('main.index'))
        return redirect(next_url)
    
    auth_manager = get_auth_manager()
    if not auth_manager:
        flash('Authentication system not available', 'error')
        return render_template('auth/error.html'), 500
    
    # Get available providers
    providers_info = auth_manager.get_provider_info()
    enabled_providers = {k: v for k, v in providers_info.items() if v.get('enabled', False)}
    
    if request.method == 'GET':
        return render_template('auth/login.html', providers=enabled_providers)
    
    # Handle POST request
    auth_method = request.form.get('auth_method', 'local')
    
    if auth_method == 'local':
        return _handle_local_login(auth_manager)
    elif auth_method == 'ldap':
        return _handle_ldap_login(auth_manager)
    elif auth_method == 'oidc':
        return _handle_oidc_login(auth_manager)
    else:
        flash('Invalid authentication method', 'error')
        return render_template('auth/login.html', providers=enabled_providers)


def _handle_local_login(auth_manager: AuthenticationManager):
    """Handle local authentication"""
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    
    if not username or not password:
        flash('Username and password are required', 'error')
        return redirect(url_for('auth.login'))
    
    # Get request info for session creation
    request_info = {
        'ip_address': request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr),
        'user_agent': request.headers.get('User-Agent', '')
    }
    
    # Authenticate user
    response = auth_manager.authenticate(username, password)
    
    if response.success:
        # Create session
        user_session = auth_manager.create_session(
            response.user, 
            AuthProvider.LOCAL, 
            request_info
        )
        
        # Store session ID in Flask session
        session['session_id'] = user_session.session_id
        session.permanent = True
        
        flash(f'Welcome, {response.user.full_name or response.user.username}!', 'success')
        
        # Redirect to next URL or dashboard
        next_url = session.pop('next_url', url_for('main.index'))
        return redirect(next_url)
    else:
        flash(response.message, 'error')
        return redirect(url_for('auth.login'))


def _handle_ldap_login(auth_manager: AuthenticationManager):
    """Handle LDAP authentication"""
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    
    if not username or not password:
        flash('Username and password are required', 'error')
        return redirect(url_for('auth.login'))
    
    # Get request info for session creation
    request_info = {
        'ip_address': request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr),
        'user_agent': request.headers.get('User-Agent', '')
    }
    
    # Authenticate user with provider hint
    response = auth_manager.authenticate(
        username, password, 
        provider_hint=AuthProvider.LDAP
    )
    
    if response.success:
        # Create session
        user_session = auth_manager.create_session(
            response.user, 
            AuthProvider.LDAP, 
            request_info
        )
        
        # Store session ID in Flask session
        session['session_id'] = user_session.session_id
        session.permanent = True
        
        flash(f'Welcome, {response.user.full_name or response.user.username}!', 'success')
        
        # Redirect to next URL or dashboard
        next_url = session.pop('next_url', url_for('main.index'))
        return redirect(next_url)
    else:
        flash(response.message, 'error')
        return redirect(url_for('auth.login'))


def _handle_oidc_login(auth_manager: AuthenticationManager):
    """Handle OIDC authentication initiation"""
    try:
        # Get OIDC provider
        oidc_provider = None
        for provider_type, provider in auth_manager.providers.items():
            if provider_type == AuthProvider.OIDC and provider.enabled:
                oidc_provider = provider
                break
        
        if not oidc_provider:
            flash('OIDC authentication is not available', 'error')
            return redirect(url_for('auth.login'))
        
        # Generate state for CSRF protection
        import secrets
        state = secrets.token_urlsafe(32)
        session['oidc_state'] = state
        
        # Build redirect URI
        redirect_uri = url_for('auth.oidc_callback', _external=True)
        
        # Get authorization URL
        auth_url, state = oidc_provider.get_authorization_url(redirect_uri, state)
        
        logger.info("Redirecting to OIDC provider for authentication")
        return redirect(auth_url)
        
    except Exception as e:
        logger.error(f"OIDC login error: {e}")
        flash('Error initiating SSO authentication', 'error')
        return redirect(url_for('auth.login'))


@bp.route('/oidc/callback')
def oidc_callback():
    """
    Handle OIDC callback after authentication
    """
    auth_manager = get_auth_manager()
    if not auth_manager:
        flash('Authentication system not available', 'error')
        return redirect(url_for('auth.login'))
    
    # Get parameters from callback
    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')
    
    # Handle errors
    if error:
        error_description = request.args.get('error_description', 'Unknown error')
        logger.warning(f"OIDC callback error: {error} - {error_description}")
        flash(f'Authentication failed: {error_description}', 'error')
        return redirect(url_for('auth.login'))
    
    # Validate state parameter
    expected_state = session.pop('oidc_state', None)
    if not state or state != expected_state:
        logger.warning("OIDC callback state mismatch - possible CSRF attack")
        flash('Authentication failed: Invalid state parameter', 'error')
        return redirect(url_for('auth.login'))
    
    if not code:
        flash('Authentication failed: No authorization code received', 'error')
        return redirect(url_for('auth.login'))
    
    try:
        # Get OIDC provider
        oidc_provider = None
        for provider_type, provider in auth_manager.providers.items():
            if provider_type == AuthProvider.OIDC and provider.enabled:
                oidc_provider = provider
                break
        
        if not oidc_provider:
            flash('OIDC authentication is not available', 'error')
            return redirect(url_for('auth.login'))
        
        # Authenticate with authorization code
        response = oidc_provider.authenticate(authorization_code=code, state=state)
        
        if response.success:
            # Get request info for session creation
            request_info = {
                'ip_address': request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr),
                'user_agent': request.headers.get('User-Agent', ''),
                'provider_session_data': response.session_data
            }
            
            # Create session
            user_session = auth_manager.create_session(
                response.user, 
                AuthProvider.OIDC, 
                request_info
            )
            
            # Store session ID in Flask session
            session['session_id'] = user_session.session_id
            session.permanent = True
            
            flash(f'Welcome, {response.user.full_name or response.user.username}!', 'success')
            
            # Redirect to next URL or dashboard
            next_url = session.pop('next_url', url_for('main.index'))
            return redirect(next_url)
        else:
            flash(response.message, 'error')
            return redirect(url_for('auth.login'))
    
    except Exception as e:
        logger.error(f"OIDC callback error: {e}", exc_info=True)
        flash('Authentication failed: System error', 'error')
        return redirect(url_for('auth.login'))


@bp.route('/logout')
def logout():
    """
    Log out current user
    """
    user = get_current_user()
    if user:
        logger.info(f"User {user.username} logging out")
    
    # Logout user (invalidates session)
    logout_user()
    
    flash('You have been logged out successfully', 'info')
    return redirect(url_for('auth.login'))


@bp.route('/profile')
@require_auth
def profile():
    """
    User profile page
    """
    user = get_current_user()
    return render_template('auth/profile.html', user=user)


@bp.route('/profile/edit', methods=['GET', 'POST'])
@require_auth
def edit_profile():
    """
    Edit user profile
    """
    user = get_current_user()
    
    if request.method == 'GET':
        return render_template('auth/edit_profile.html', user=user)
    
    # Handle POST request
    full_name = request.form.get('full_name', '').strip()
    email = request.form.get('email', '').strip()
    timezone = request.form.get('timezone', 'UTC')
    language = request.form.get('language', 'en')
    
    try:
        # Update user info
        user.full_name = full_name
        user.email = email
        user.timezone = timezone
        user.language = language
        
        from database import db
        db.session.commit()
        
        flash('Profile updated successfully', 'success')
        return redirect(url_for('auth.profile'))
        
    except Exception as e:
        from database import db
        db.session.rollback()
        logger.error(f"Failed to update profile for {user.username}: {e}")
        flash('Error updating profile', 'error')
        return render_template('auth/edit_profile.html', user=user)


@bp.route('/change-password', methods=['GET', 'POST'])
@require_auth
def change_password():
    """
    Change user password (local auth only)
    """
    user = get_current_user()
    
    # Only allow password changes for local auth users
    if user.auth_provider != AuthProvider.LOCAL:
        flash('Password changes are not supported for your authentication method', 'warning')
        return redirect(url_for('auth.profile'))
    
    if request.method == 'GET':
        return render_template('auth/change_password.html')
    
    # Handle POST request
    current_password = request.form.get('current_password', '')
    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')
    
    if not current_password or not new_password or not confirm_password:
        flash('All fields are required', 'error')
        return render_template('auth/change_password.html')
    
    if new_password != confirm_password:
        flash('New passwords do not match', 'error')
        return render_template('auth/change_password.html')
    
    try:
        # Get local auth provider
        auth_manager = get_auth_manager()
        local_provider = None
        
        for provider_type, provider in auth_manager.providers.items():
            if provider_type == AuthProvider.LOCAL:
                local_provider = provider
                break
        
        if not local_provider:
            flash('Local authentication is not available', 'error')
            return redirect(url_for('auth.profile'))
        
        # Change password
        success = local_provider.change_password(
            user.username, 
            current_password, 
            new_password
        )
        
        if success:
            flash('Password changed successfully', 'success')
            return redirect(url_for('auth.profile'))
        else:
            flash('Failed to change password', 'error')
            return render_template('auth/change_password.html')
            
    except Exception as e:
        logger.error(f"Password change error for {user.username}: {e}")
        flash(str(e), 'error')
        return render_template('auth/change_password.html')


@bp.route('/admin/users')
@admin_required
def admin_users():
    """
    Admin page for user management
    """
    users = User.query.order_by(User.created_at.desc()).all()
    
    # Get authentication stats
    auth_manager = get_auth_manager()
    stats = auth_manager.get_authentication_stats() if auth_manager else {}
    
    return render_template('auth/admin_users.html', users=users, stats=stats)


@bp.route('/admin/users/<int:user_id>')
@admin_required
def admin_user_detail(user_id):
    """
    Admin page for individual user details
    """
    user = User.query.get_or_404(user_id)
    
    # Get user sessions
    active_sessions = [s for s in user.sessions if s.is_active]
    
    return render_template('auth/admin_user_detail.html', user=user, active_sessions=active_sessions)


@bp.route('/admin/users/<int:user_id>/disable', methods=['POST'])
@admin_required
def admin_disable_user(user_id):
    """
    Admin function to disable a user
    """
    user = User.query.get_or_404(user_id)
    current_user = get_current_user()
    
    # Prevent disabling self
    if user.id == current_user.id:
        flash('You cannot disable your own account', 'error')
        return redirect(url_for('auth.admin_user_detail', user_id=user_id))
    
    try:
        from models.user import AccountStatus
        user.status = AccountStatus.DISABLED
        
        # Invalidate all user sessions
        auth_manager = get_auth_manager()
        if auth_manager:
            auth_manager.invalidate_all_user_sessions(user.id)
        
        from database import db
        db.session.commit()
        
        logger.info(f"Admin {current_user.username} disabled user {user.username}")
        flash(f'User {user.username} has been disabled', 'success')
        
    except Exception as e:
        from database import db
        db.session.rollback()
        logger.error(f"Failed to disable user {user.username}: {e}")
        flash('Error disabling user', 'error')
    
    return redirect(url_for('auth.admin_user_detail', user_id=user_id))


@bp.route('/admin/users/<int:user_id>/enable', methods=['POST'])
@admin_required
def admin_enable_user(user_id):
    """
    Admin function to enable a user
    """
    user = User.query.get_or_404(user_id)
    current_user = get_current_user()
    
    try:
        from models.user import AccountStatus
        user.status = AccountStatus.ACTIVE
        user.unlock_account()  # Also unlock if locked
        
        from database import db
        db.session.commit()
        
        logger.info(f"Admin {current_user.username} enabled user {user.username}")
        flash(f'User {user.username} has been enabled', 'success')
        
    except Exception as e:
        from database import db
        db.session.rollback()
        logger.error(f"Failed to enable user {user.username}: {e}")
        flash('Error enabling user', 'error')
    
    return redirect(url_for('auth.admin_user_detail', user_id=user_id))


@bp.route('/api/session/check')
def check_session():
    """
    API endpoint to check session validity
    """
    user = get_current_user()
    
    if user:
        return jsonify({
            'authenticated': True,
            'user': {
                'id': user.id,
                'username': user.username,
                'full_name': user.full_name,
                'role': user.role.value,
                'auth_provider': user.auth_provider.value
            }
        })
    else:
        return jsonify({
            'authenticated': False
        }), 401


@bp.route('/api/logout', methods=['POST'])
def api_logout():
    """
    API endpoint for logout
    """
    logout_user()
    return jsonify({'success': True, 'message': 'Logged out successfully'})


# Error handlers for auth blueprint
@bp.errorhandler(401)
def auth_unauthorized(error):
    """Handle unauthorized access"""
    if request.is_json:
        return jsonify({
            'error': 'Unauthorized',
            'message': 'Authentication required',
            'status': 401
        }), 401
    else:
        flash('Please log in to access this page', 'warning')
        session['next_url'] = request.url
        return redirect(url_for('auth.login'))


@bp.errorhandler(403)
def auth_forbidden(error):
    """Handle forbidden access"""
    if request.is_json:
        return jsonify({
            'error': 'Forbidden',
            'message': 'Insufficient permissions',
            'status': 403
        }), 403
    else:
        flash('You do not have permission to access this page', 'error')
        return redirect(url_for('main.index'))