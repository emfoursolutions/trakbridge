# Migration Order Documentation

This document tracks the logical order of migrations in TrakBridge to help with understanding the database schema evolution.

## Migration Naming Convention (Going Forward)

**New migrations should use descriptive names following this pattern:**
```
add_feature_description.py
update_table_modification.py  
remove_deprecated_feature.py
fix_data_consistency_issue.py
```

**Avoid:**
- Auto-generated hash prefixes (e.g., `c530e1fd8e8d_`)
- Date prefixes in filenames
- Phase/version references (e.g., `phase5`, `v2.0`)

## Current Migration Chain

### Initial Schema
1. `consolidated_initial_migration.py` - Complete initial database schema (new deployments)

### Sequential Migrations (existing deployments)
2. `0a9c5469abc6_add_authentication_tables_for_users_and_.py` - User authentication system
3. `c530e1fd8e8d_add_tls_version_selection_to_tak_servers.py` - TAK server TLS configuration  
4. `e2f64ceef0b8_add_cot_type_mode_column_to_streams_.py` - CoT type mode for streams
5. `3120f5bf60a4_add_provider_field_to_user_sessions_.py` - Multi-provider authentication
6. `add_timezone_to_user_sessions.py` - User session timezone support

### Feature Migrations
7. `add_callsign_mapping_tables.py` - Callsign mapping functionality
8. `add_enabled_column_to_callsign_mappings.py` - Enable/disable tracker control
9. `add_stream_tak_servers_junction.py` - Multi-server stream support
10. `add_database_performance_indexes.py` - Performance optimization indexes

### Merge & Current
11. `merge_heads_migration.py` - Resolves multiple migration heads
12. `add_enabled_column_indexes.py` - Performance indexes for tracker filtering

## Migration Status Commands

```bash
# View current migration status
flask db current

# View all migration heads
flask db heads

# View migration history
flask db history

# Apply all pending migrations
flask db upgrade

# Apply specific migration
flask db upgrade <revision_id>
```

## Troubleshooting

### Multiple Heads Issue
If you encounter "Multiple head revisions" error:
```bash
# View heads
flask db heads

# Merge heads (if needed)
flask db merge <revision1> <revision2> -m "Merge migration heads"

# Apply merged migration
flask db upgrade
```

### Migration Dependencies
- New deployments: Use `consolidated_initial_migration.py` as starting point
- Existing deployments: Follow sequential migration chain through `merge_heads_migration.py`
- All new migrations should depend on `merge_heads_migration.py` or later

## Best Practices

1. **Always test migrations** on development database first
2. **Backup production database** before applying migrations
3. **Use descriptive commit messages** for migration changes
4. **Include rollback strategy** in migration planning
5. **Document schema changes** in migration docstrings
6. **Test both upgrade and downgrade** paths when possible

## Schema Documentation

For current database schema documentation, see:
- `models/` directory for SQLAlchemy model definitions  
- `database.py` for database configuration
- Individual migration files for change history