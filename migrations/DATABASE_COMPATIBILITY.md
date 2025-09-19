# Database Compatibility for config_version Migration

The consolidated `config_version` migration has been designed for full compatibility across SQLite, PostgreSQL, and MariaDB 11+.

## Cross-Database Features

### Column Type Selection
- **PostgreSQL**: Uses `TIMESTAMP(timezone=True)` for proper timezone support
- **MariaDB 11+**: Uses `TIMESTAMP()` with microsecond precision support
- **SQLite**: Falls back to `DateTime()` for compatibility

### Timestamp Generation
- **PostgreSQL**: Uses native `NOW()` function with timezone awareness
- **MariaDB 11+**: Uses native `NOW()` function for consistent timestamps
- **SQLite**: Uses Python `datetime.now(timezone.utc)` for UTC consistency

### Index Operations
- **SQLite**: Uses `batch_alter_table()` context manager for safe schema changes
- **PostgreSQL/MariaDB**: Uses direct `op.create_index()`/`op.drop_index()` operations
- **All databases**: Includes existence checking to prevent errors

### Schema Inspection
- **Case-insensitive** column name checking for cross-database compatibility
- **Table existence** verification before index operations
- **Index existence** checking before creation/deletion attempts

## Database-Specific Optimizations

### PostgreSQL
```sql
-- Column creation with timezone support
ALTER TABLE streams ADD COLUMN config_version TIMESTAMP WITH TIME ZONE;

-- Default value assignment
UPDATE streams SET config_version = NOW() WHERE config_version IS NULL;
```

### MariaDB 11+
```sql
-- Column creation with TIMESTAMP support
ALTER TABLE streams ADD COLUMN config_version TIMESTAMP;

-- Default value assignment
UPDATE streams SET config_version = NOW() WHERE config_version IS NULL;
```

### SQLite
```sql
-- Column creation with DateTime
ALTER TABLE streams ADD COLUMN config_version DATETIME;

-- Parameterized update with UTC timestamp
UPDATE streams SET config_version = ? WHERE config_version IS NULL;
```

## Error Handling

The migration includes comprehensive error handling:
- **Graceful fallbacks** if database operations fail
- **Existence checking** to prevent duplicate operations
- **Exception catching** to continue migration on non-critical errors
- **Database dialect detection** for appropriate operation selection

## Testing

The migration has been tested with:
- ✅ SQLite (development/testing)
- ✅ Migration upgrade/downgrade cycles
- ✅ Existing data preservation
- ✅ Index operations safety
- ✅ App startup verification

For PostgreSQL and MariaDB testing, deploy with:
```bash
# PostgreSQL
docker-compose --profile postgres up -d
flask db upgrade

# MariaDB
docker-compose --profile mysql up -d
flask db upgrade
```

## Migration Path

Clean migration sequence for new deployments:
```
f085153337e8 → consolidated_config_version_migration
```

This replaces the previous complex migration tree and provides users with a single, reliable migration to apply.