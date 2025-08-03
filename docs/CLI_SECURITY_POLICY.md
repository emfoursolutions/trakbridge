# CLI Security Policy

## Overview

TrakBridge implements a secure-by-design approach to user management by restricting administrative operations to the web interface only.

## Security Design Principles

### 1. Web-Only User Management
- **No CLI user creation commands**: Admin users can only be created through the bootstrap process or web interface
- **No CLI role management**: User roles can only be modified through the web interface by existing administrators
- **No CLI password resets**: Password management is handled exclusively through the web interface

### 2. Bootstrap Security
- **One-time admin creation**: Initial admin user is created automatically on first startup only
- **Secure default credentials**: `admin` / `TrakBridge-Setup-2025!` with mandatory password change
- **Bootstrap protection**: Once any admin exists, automatic creation is permanently disabled

### 3. Audit Trail Requirements
- **All admin actions logged**: User creation, role changes, and account modifications are logged
- **Web-based approval**: Admin role elevation requires existing admin approval through web interface
- **Session tracking**: All administrative actions are tied to authenticated web sessions

## Implemented Restrictions

### CLI Commands Available
```bash
# Version management (read-only)
python -m flask version show
python -m flask version validate

# Database management (system-level)
python -m flask db upgrade
python -m flask db migrate
```

### CLI Commands Explicitly Prohibited
```bash
# These commands DO NOT EXIST and will never be implemented
python -m flask auth create-admin      # PROHIBITED
python -m flask auth create-user       # PROHIBITED  
python -m flask auth promote-user      # PROHIBITED
python -m flask auth reset-password    # PROHIBITED
```

## Security Benefits

### 1. Prevents Privilege Escalation
- **No CLI admin creation**: Prevents unauthorized admin account creation
- **Session-based authorization**: All admin actions require web authentication
- **Audit trail**: Complete logging of who made what changes

### 2. Access Control
- **Web interface only**: Centralizes all user management through authenticated web interface
- **Role-based permissions**: Admin functions only available to authenticated admin users
- **Last admin protection**: Cannot remove admin role from last administrator

### 3. Compliance and Monitoring
- **Comprehensive logging**: All user management actions are logged with timestamps and operator details
- **Non-repudiation**: Actions are tied to authenticated user sessions
- **Change tracking**: Complete audit trail for compliance requirements

## Implementation Details

### Bootstrap Service
- **File**: `services/auth/bootstrap_service.py`
- **Purpose**: One-time initial admin creation on first startup
- **Security**: Creates `/app/data/.bootstrap_completed` flag to prevent repeated execution

### Web Interface Security
- **Route Protection**: All admin routes use `@admin_required` decorator
- **CSRF Protection**: All forms include CSRF tokens
- **Input Validation**: Comprehensive validation for all user inputs
- **Provider Restrictions**: External users (LDAP/OIDC) have read-only fields

### Audit Logging
All user management actions are logged at INFO level:
```
[INFO] Admin alice created user bob with role operator
[INFO] Admin alice changed user bob role to admin  
[INFO] Admin alice disabled user charlie
[INFO] Admin alice reset password for user david
```

## Maintenance

### Adding New CLI Commands
- **Policy**: New CLI commands must not provide user management functionality
- **Review Required**: All new CLI commands must be reviewed for security implications
- **Documentation**: Any new CLI commands must be documented in this policy

### Emergency Access
- **Container Restart**: If admin access is lost, restart container to trigger bootstrap (if no admins exist)
- **Database Recovery**: Database-level user management should only be performed by system administrators with direct database access
- **Backup Restoration**: User data can be restored from database backups

## Compliance Notes

This security model ensures:
- **SOC 2 Compliance**: Comprehensive audit logging and access controls
- **ISO 27001**: Principle of least privilege and secure access management
- **NIST Cybersecurity Framework**: Identity and access management best practices
- **Enterprise Security**: Centralized user management with complete audit trails

---

**Security Review Date**: 2025-07-28  
**Next Review**: 2026-01-28  
**Policy Version**: 1.0.0