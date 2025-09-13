# Migration Naming Convention

## Quick Reference

When creating new migrations, use descriptive names without auto-generated prefixes:

### ✅ Good Examples
```
add_user_preferences_table.py
update_stream_polling_intervals.py  
remove_deprecated_auth_fields.py
fix_tak_server_connection_indexes.py
add_notification_system.py
```

### ❌ Avoid These Patterns
```
c530e1fd8e8d_add_feature.py           # Auto-generated hash prefix
2025_01_12_add_feature.py             # Date prefix
phase5_tracker_filtering.py           # Phase/version reference  
add_enabled_index_phase5.py           # Phase reference (old pattern)
```

## Creating New Migrations

### Step 1: Generate Migration
```bash
# Use descriptive message
flask db migrate -m "Add user notification preferences table"
```

### Step 2: Rename Generated File
If Flask-Migrate generates a hash-prefixed file, rename it:
```bash
# From: a1b2c3d4e5f6_add_user_notification_preferences_table.py
# To:   add_user_notification_preferences_table.py
```

### Step 3: Update Revision ID
Edit the migration file to match the filename:
```python
# Change revision ID to match filename
revision = 'add_user_notification_preferences_table'
```

### Step 4: Set Down Revision
Always base new migrations on the latest:
```python
down_revision = 'merge_heads_migration'  # or latest migration
```

## Migration Content Guidelines

### Docstring Template
```python
"""Add user notification preferences table

Revision ID: add_user_notification_preferences_table
Revises: merge_heads_migration
Create Date: 2025-01-12 15:30:00.000000

Adds support for user-specific notification preferences including:
- Email notification settings
- Push notification preferences  
- Notification frequency controls
"""
```

### Safe Migration Patterns
```python
def upgrade():
    """Add new functionality safely"""
    # Check if table/column exists before creating
    if not table_exists('user_preferences'):
        op.create_table(...)
    
    if not column_exists('users', 'notification_enabled'):
        op.add_column('users', sa.Column(...))

def downgrade():
    """Remove functionality safely"""
    # Check if exists before dropping
    if column_exists('users', 'notification_enabled'):
        op.drop_column('users', 'notification_enabled')
        
    if table_exists('user_preferences'):
        op.drop_table('user_preferences')
```

## Testing Migrations

```bash
# Test upgrade
flask db upgrade add_user_notification_preferences_table

# Test downgrade  
flask db downgrade -1

# Re-apply
flask db upgrade
```

This convention ensures migrations are:
- **Readable**: Clear purpose from filename
- **Maintainable**: No cryptic hash prefixes
- **Consistent**: Standardized naming pattern
- **Future-proof**: No version/phase references