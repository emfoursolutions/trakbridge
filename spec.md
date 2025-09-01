# Tracker Callsign Mapping Feature Specification

## Overview
Add the ability for users to configure custom callsigns for individual trackers detected by GPS provider plugins in the tracker category. This feature enables operational flexibility by allowing users to assign meaningful identifiers instead of using raw device identifiers like IMEIs or serial numbers.

**Key Design Principles:**
- **Minimal codebase changes** to avoid breaking existing functionality
- **Optional plugin enhancement** - plugins can choose to implement or use current hardcoded behavior
- **Clean separation** - checkbox toggle controls between custom mapping and current behavior
- **Per-callsign CoT types** for advanced operational flexibility
- **Stream isolation** - each stream has completely independent callsign configurations

## Scope
This feature applies to plugins with category metadata set to "tracker":
- Garmin InReach Plugin
- SPOT Tracker Plugin  
- Traccar Plugin

## User Experience

### Stream Configuration Workflow
1. **API Configuration**: User enters plugin credentials and connection details as currently implemented
2. **Callsign Mapping Toggle**: User checks "Enable custom callsign mapping" checkbox
3. **Immediate Discovery**: Upon checking the checkbox, form immediately discovers and displays all trackers
4. **Field Selection & Assignment**: Form shows:
   - Dropdown of available identifier fields from tracker data
   - Table of discovered trackers with columns:
     - Identifier (from selected field)
     - Current Name (from plugin's default extraction)
     - Assigned Callsign (editable, pre-populated with cleaned identifier)
     - CoT Type (dropdown, optional per-callsign override)
5. **Refresh Capability**: "Refresh Trackers" button to re-discover without losing existing assignments
6. **Error Handling**: Radio buttons for fallback vs skip behavior
7. **Save Stream**: Complete configuration saved to database

### Default Behavior (Checkbox Unchecked)
- **Identical to current functionality** - no code changes to existing behavior
- Plugin uses hardcoded extraction (e.g., Garmin uses "Map Display Name")
- Stream-level CoT type applies to all trackers
- No additional database queries or processing overhead

### Ongoing Management
- **Stream Edit Interface**: Users can modify callsign mappings through existing stream edit page
- **Stream Detail Page**: Display callsign configuration section showing current mappings
- **New Tracker Auto-Assignment**: When new trackers are discovered:
  - Auto-assigned callsigns using smart defaults (cleaned identifier values)
  - Existing mappings preserved when refreshing tracker list
  - Background detection with optional user notifications

### Error Handling Options
Users can configure per-stream behavior for mapping failures:
- **Fallback Mode**: Use plugin's hardcoded extraction if callsign mapping fails
- **Skip Mode**: Exclude problematic trackers from CoT output and log errors

## Technical Architecture

### Database Schema - Separate Table Approach
Create dedicated `CallsignMapping` table for scalability and per-callsign CoT types:

```python
class CallsignMapping(db.Model, TimestampMixin):
    __tablename__ = "callsign_mappings"
    
    id = db.Column(db.Integer, primary_key=True)
    stream_id = db.Column(db.Integer, db.ForeignKey("streams.id"), nullable=False)
    identifier_value = db.Column(db.String(255), nullable=False)  # Raw identifier (IMEI, device_name, etc.)
    custom_callsign = db.Column(db.String(100), nullable=False)   # User-assigned callsign
    cot_type = db.Column(db.String(50), nullable=True)           # Per-callsign CoT type override
    
    # Relationships
    stream = db.relationship("Stream", back_populates="callsign_mappings")
    
    # Constraints
    __table_args__ = (
        db.UniqueConstraint('stream_id', 'identifier_value', name='unique_stream_identifier'),
    )

# Minimal additions to Stream table
class Stream(db.Model, TimestampMixin):
    # ... existing fields unchanged ...
    
    # New minimal fields
    enable_callsign_mapping = db.Column(db.Boolean, default=False)
    callsign_identifier_field = db.Column(db.String(100), nullable=True)  # Selected field name
    callsign_error_handling = db.Column(db.String(20), default="fallback")  # "fallback" or "skip"
    enable_per_callsign_cot_types = db.Column(db.Boolean, default=False)  # Feature toggle
    
    # Relationship
    callsign_mappings = db.relationship("CallsignMapping", back_populates="stream", cascade="all, delete-orphan")
```

### Plugin Interface Enhancement
Create optional `CallsignMappable` interface - plugins choose whether to implement:

```python
class CallsignMappable:
    def get_available_fields(self) -> List[FieldMetadata]:
        """Return available identifier fields with metadata"""
        pass
        
    def apply_callsign_mapping(self, tracker_data: List[dict], field_name: str, callsign_map: dict) -> None:
        """Apply callsign mappings to tracker data in-place"""
        pass

class FieldMetadata:
    name: str          # Field name in data (e.g., "imei")
    display_name: str  # User-friendly name (e.g., "Device IMEI") 
    type: str         # Data type (e.g., "string")
```

**Plugin Implementation Strategy:**
- **Optional Implementation**: Plugins can choose to implement `CallsignMappable` or not
- **Fallback Behavior**: If mapping fails or plugin doesn't implement interface, use plugin's existing hardcoded extraction
- **Zero Breaking Changes**: Existing plugins continue working exactly as before

### Plugin Implementation Guidelines
Tracker plugins can optionally implement `CallsignMappable` for enhanced functionality:

#### Garmin InReach Plugin
- **Current behavior (fallback)**: Uses "Map Display Name" from extended data
- **Available fields**: `["imei", "name", "uid"]`
- **Recommended field**: `"imei"` (most stable identifier)
- **Implementation**: Extract identifier from selected field, apply mapping to location['name']

#### SPOT Tracker Plugin  
- **Current behavior (fallback)**: Uses device name from feed data
- **Available fields**: `["device_name", "feed_id", "messenger_name"]`
- **Recommended field**: `"device_name"`
- **Implementation**: Extract device name, apply mapping to location['name']

#### Traccar Plugin
- **Current behavior (fallback)**: Uses device name from API
- **Available fields**: `["name", "device_id", "unique_id"]` 
- **Recommended field**: `"name"`
- **Implementation**: Extract device name, apply mapping to location['name']

### Data Processing Flow with Fallback Strategy
1. **Plugin fetches raw tracker data** from provider API
2. **Check callsign mapping enabled**:
   - If `stream.enable_callsign_mapping == False`: Use current plugin behavior (no changes)
   - If `stream.enable_callsign_mapping == True`: Proceed with custom mapping
3. **Apply callsign mapping** (when enabled):
   - Load callsign mappings from `CallsignMapping` table
   - If plugin implements `CallsignMappable`: Use `apply_callsign_mapping()`
   - If plugin doesn't implement interface: Use fallback extraction
   - Handle mapping failures per user preference (fallback/skip)
4. **Apply per-callsign CoT types** (when enabled):
   - Check if tracker has custom CoT type in mapping
   - Override stream CoT type if custom type exists
   - Fall back to stream CoT type if no override
5. **Convert to CoT format** with mapped callsigns and CoT types
6. **Send CoT messages** to TAK servers

### CoT Type Hierarchy
Per-callsign CoT types follow this precedence:
1. **Per-callsign CoT type** (if `enable_per_callsign_cot_types == True` and mapping exists)
2. **Stream default CoT type** (fallback for all trackers)

### Stream Worker Integration
Minimal changes to existing stream worker logic:

```python
async def _apply_callsign_mapping(self, locations: List[Dict]) -> None:
    """Apply callsign mapping to locations if configured"""
    # Early exit if callsign mapping not enabled (preserves current behavior)
    if not getattr(self.stream, 'enable_callsign_mapping', False):
        return
    
    # Load mappings from database table
    callsign_mappings = self._load_callsign_mappings()
    if not callsign_mappings:
        return
    
    # Apply mappings with fallback behavior
    for location in locations:
        identifier = self._extract_identifier(location)
        if identifier in callsign_mappings:
            mapping = callsign_mappings[identifier]
            location['name'] = mapping.custom_callsign
            
            # Apply per-callsign CoT type if enabled and configured
            if (self.stream.enable_per_callsign_cot_types and 
                mapping.cot_type):
                location['cot_type'] = mapping.cot_type
```

## Implementation Strategy - Clean & Minimal

### Phase 1: Database Foundation (Week 1)
**Goal**: Establish database schema without breaking existing functionality

**Tasks**:
1. **Create CallsignMapping model** - new table with proper relationships
2. **Add minimal fields to Stream model** - 4 new boolean/string fields only
3. **Create cross-database compatible Alembic migration** - add new table and columns
4. **Remove existing callsign_* fields** - clean slate approach

**Files Modified**: `models/stream.py`, `models/__init__.py`, new `models/callsign_mapping.py`
**Migration**: Single migration file for all changes, tested on MySQL, PostgreSQL, and SQLite
**Risk**: Low - additive changes only

**Database Compatibility Requirements**:
- **MySQL Support**: Use appropriate data types and constraints compatible with MySQL 8.0+
- **PostgreSQL Support**: Ensure compatibility with PostgreSQL 12+
- **SQLite Support**: Use SQLite-compatible syntax for constraints and data types
- **Migration Testing**: Test migration on all three database systems
- **Data Type Selection**: Use SQLAlchemy types that map correctly across all databases

### Phase 2: Plugin Interface (Week 1-2)
**Goal**: Establish optional plugin interface without breaking existing plugins

**Tasks**:
1. **Update base_plugin.py** - add `CallsignMappable` interface (already exists)
2. **Update tracker plugins** - implement interface methods (already partially implemented)
3. **Remove hardcoded API mappings** - clean up `routes/api.py`
4. **Add fallback logic** - ensure plugins work without interface

**Files Modified**: `plugins/base_plugin.py`, `plugins/*_plugin.py`, `routes/api.py`
**Risk**: Low - existing plugins continue working via fallback

### Phase 3: Stream Worker Logic (Week 2)
**Goal**: Integrate callsign mapping into data processing flow

**Tasks**:
1. **Update stream_worker.py** - add callsign application logic
2. **Add database loading methods** - efficient callsign mapping queries
3. **Implement CoT type overrides** - per-callsign CoT type logic
4. **Preserve current behavior** - early exit when feature disabled

**Files Modified**: `services/stream_worker.py`, new service methods
**Risk**: Low - guarded by feature toggles

### Phase 4: User Interface (Week 2-3)
**Goal**: Build callsign configuration UI

**Tasks**:
1. **Update stream forms** - add callsign mapping section with checkbox toggle
2. **Add tracker discovery** - immediate discovery on checkbox enable
3. **Build callsign table** - editable table with CoT type dropdowns
4. **Update stream detail page** - display current callsign configuration

**Files Modified**: `templates/create_stream.html`, `templates/edit_stream.html`, `templates/stream_detail.html`
**New Routes**: `/streams/discover-trackers`, `/streams/<id>/callsign-mappings`
**Risk**: Medium - UI changes require testing

### Phase 5: API & Routes (Week 3)
**Goal**: Support UI with clean API endpoints

**Tasks**:
1. **Add callsign management routes** - CRUD operations for mappings
2. **Update stream operations service** - handle callsign data in stream updates
3. **Add tracker discovery endpoint** - live tracker preview functionality
4. **Update existing routes** - minimal changes to support new fields

**Files Modified**: `routes/streams.py`, `routes/api.py`, `services/stream_operations_service.py`
**Risk**: Low - additive API changes

## Deployment Strategy - Zero Migration Approach

### No Migration Required
- **Fresh implementation** on new branch from main
- **Clean database schema** - no existing callsign data to migrate
- **Feature toggles** ensure backward compatibility
- **Default behavior preserved** for all existing functionality

### Rollback Safety
- **Feature can be disabled** via database toggles
- **No breaking changes** to existing code paths
- **Isolated new functionality** in separate table and services

## Acceptance Criteria - Comprehensive Testing

### Core Functionality
- [ ] **Checkbox toggle works**: Enabling shows immediate tracker discovery
- [ ] **Field selection works**: User can select identifier field from dropdown
- [ ] **Tracker discovery works**: Live preview shows actual tracker data
- [ ] **Callsign assignment works**: User can assign custom callsigns with defaults
- [ ] **CoT type override works**: Per-callsign CoT types override stream default
- [ ] **Error handling works**: Fallback/skip modes handle mapping failures correctly

### Backward Compatibility
- [ ] **Existing streams unchanged**: Current functionality works exactly as before
- [ ] **Plugin fallback works**: Non-CallsignMappable plugins use hardcoded extraction
- [ ] **Performance unchanged**: No overhead when feature disabled
- [ ] **No breaking changes**: All existing APIs and workflows preserved

### Data Integrity
- [ ] **Stream isolation**: Each stream's callsigns completely independent
- [ ] **Identifier uniqueness**: No duplicate identifiers within same stream
- [ ] **Cascade deletion**: Callsign mappings deleted when stream deleted
- [ ] **Transaction safety**: All database operations atomic

### User Experience
- [ ] **Stream detail shows mappings**: Current callsign configuration visible
- [ ] **Edit form populates**: Existing callsign mappings load in edit mode
- [ ] **Refresh preserves assignments**: Re-discovery keeps existing callsign assignments
- [ ] **Validation prevents conflicts**: UI prevents invalid configurations

### Security & Performance
- [ ] **Access control**: Only authorized users can modify callsign mappings
- [ ] **Input validation**: All callsign values properly sanitized
- [ ] **Database performance**: Efficient queries with proper indexing
- [ ] **Memory efficiency**: Minimal memory footprint for mapping operations

## Database Migration Specification

### Cross-Database Compatibility
The migration must work identically across all supported database systems:

**Supported Databases**:
- **MySQL 8.0+**: Production database system
- **PostgreSQL 12+**: Alternative production database
- **SQLite 3.25+**: Development and testing database

**Migration File Structure**:
```python
"""Create callsign_mappings table and update streams

Revision ID: [generated_id]
Revises: [previous_revision]
Create Date: [timestamp]
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

def upgrade():
    # Create callsign_mappings table - cross-database compatible
    op.create_table('callsign_mappings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('stream_id', sa.Integer(), nullable=False),
        sa.Column('identifier_value', sa.String(255), nullable=False),
        sa.Column('custom_callsign', sa.String(100), nullable=False),
        sa.Column('cot_type', sa.String(50), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['stream_id'], ['streams.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('stream_id', 'identifier_value', name='unique_stream_identifier')
    )
    
    # Add new columns to streams table
    op.add_column('streams', sa.Column('enable_callsign_mapping', sa.Boolean(), nullable=False, server_default='0'))
    op.add_column('streams', sa.Column('callsign_identifier_field', sa.String(100), nullable=True))
    op.add_column('streams', sa.Column('callsign_error_handling', sa.String(20), nullable=False, server_default='fallback'))
    op.add_column('streams', sa.Column('enable_per_callsign_cot_types', sa.Boolean(), nullable=False, server_default='0'))
    
    # Remove existing callsign fields (if they exist)
    # Handle gracefully in case they don't exist
    try:
        op.drop_column('streams', 'callsign_field')
        op.drop_column('streams', 'callsign_mappings')
        op.drop_column('streams', 'callsign_error_handling_old')
        op.drop_column('streams', 'callsign_last_updated')
    except Exception:
        # Fields may not exist, continue
        pass

def downgrade():
    # Reverse the changes
    op.drop_column('streams', 'enable_per_callsign_cot_types')
    op.drop_column('streams', 'callsign_error_handling')
    op.drop_column('streams', 'callsign_identifier_field')
    op.drop_column('streams', 'enable_callsign_mapping')
    op.drop_table('callsign_mappings')
```

**Cross-Database Considerations**:
- **Boolean Fields**: Use `sa.Boolean()` with explicit `server_default` for compatibility
- **String Lengths**: Specify explicit lengths for VARCHAR fields
- **Foreign Keys**: Use `ondelete='CASCADE'` for consistent behavior
- **Unique Constraints**: Name constraints explicitly for cross-database compatibility
- **DateTime Fields**: Use `sa.DateTime()` without timezone for SQLite compatibility
- **Default Values**: Use `server_default` instead of `default` for database-level defaults

**Testing Strategy**:
```bash
# Test migration on all databases
DB_TYPE=sqlite flask db upgrade
DB_TYPE=mysql flask db upgrade  
DB_TYPE=postgresql flask db upgrade

# Test rollback on all databases
DB_TYPE=sqlite flask db downgrade
DB_TYPE=mysql flask db downgrade
DB_TYPE=postgresql flask db downgrade
```

## Test-Driven Development (TDD) Requirements

### TDD Implementation Mandate
**All new callsign mapping functionality MUST follow strict TDD principles:**

1. **Write a failing test** that defines the desired function or improvement
2. **Run the test** to confirm it fails as expected  
3. **Write minimal code** to make the test pass
4. **Run the test** to confirm success
5. **Refactor code** to improve design while keeping tests green
6. **Repeat the cycle** for each new feature or bugfix

### Integration with Existing Testing System
**All callsign mapping tests will be added to the existing testing structure to increase overall coverage:**

#### Unit Tests (Added to existing files)
**Models** - **Add to `tests/unit/test_models.py`**:
```python
class TestCallsignMappingModel:
    """Test the CallsignMapping model - integrated with existing model tests"""
    
    def test_callsign_mapping_creation(self, app, db_session):
        """Test CallsignMapping model creation and validation"""
        with app.app_context():
            # Create test stream first (using existing stream test patterns)
            stream = Stream(name="Test Stream", plugin_type="garmin")
            db_session.add(stream)
            db_session.commit()
            
            # Test CallsignMapping creation
            mapping = CallsignMapping(
                stream_id=stream.id,
                identifier_value="ABC123",
                custom_callsign="Alpha-1",
                cot_type="a-f-G-U-C"
            )
            db_session.add(mapping)
            db_session.commit()
            
            assert mapping.id is not None
            assert mapping.stream_id == stream.id
            assert mapping.custom_callsign == "Alpha-1"

    def test_stream_callsign_relationship(self, app, db_session):
        """Test Stream <-> CallsignMapping relationship - follows existing test patterns"""
        # Test cascade deletion, foreign key constraints

    def test_callsign_mapping_uniqueness(self, app, db_session):
        """Test unique constraint on stream_id + identifier_value"""
        # Test database constraint enforcement using existing test utilities
```

**Plugin Interface** - **Add to `tests/unit/test_plugins.py`**:
```python
class TestCallsignMappingPlugins:
    """Test callsign mapping functionality in existing plugin tests"""
    
    def test_garmin_plugin_get_available_fields(self):
        """Test Garmin plugin returns correct field metadata"""
        # Integrate with existing Garmin plugin tests

    def test_spot_plugin_apply_callsign_mapping(self):
        """Test SPOT plugin applies mappings correctly"""  
        # Integrate with existing SPOT plugin tests

    def test_traccar_plugin_fallback_behavior(self):
        """Test Traccar plugin works without CallsignMappable interface"""
        # Test graceful degradation using existing plugin test fixtures
```

**Services** - **Add to `tests/unit/test_services.py`**:
```python
class TestCallsignServices:
    """Test callsign services - integrated with existing service tests"""
    
    def test_stream_worker_callsign_application(self, app, db_session):
        """Test stream worker applies callsigns correctly"""
        # Use existing stream worker test fixtures
        # Test early exit when disabled, mapping when enabled, CoT type overrides

    def test_stream_operations_service_callsign_crud(self, app, db_session):
        """Test stream operations service handles callsign CRUD"""
        # Integrate with existing StreamOperationsService tests
```

#### Integration Tests (New files but using existing patterns)
**Database Operations** - **New file: `tests/integration/test_callsign_database.py`**:
```python
"""Integration tests for callsign database operations - follows existing integration patterns"""

import pytest
from tests.conftest import app, db_session  # Use existing fixtures

@pytest.mark.integration
class TestCallsignDatabaseIntegration:
    """Test callsign database operations across all database types"""
    
    def test_callsign_mapping_database_operations(self, app, db_session):
        """Test full database CRUD cycle - uses existing database test patterns"""
        # Test on SQLite (existing), MySQL, PostgreSQL using existing test utilities
        
    @pytest.mark.parametrize("db_type", ["sqlite", "mysql", "postgresql"])
    def test_migration_cross_database(self, db_type):
        """Test migration works on all supported databases"""
        # Use existing migration test patterns from test_migrations.py
```

**API Endpoints** - **Add to `tests/unit/test_routes.py`**:
```python
class TestCallsignRoutes:
    """Test callsign API routes - integrated with existing route tests"""
    
    def test_tracker_discovery_endpoint(self, client, authenticated_client, app):
        """Test live tracker discovery API"""
        # Use existing client fixtures and authentication patterns

    def test_callsign_management_endpoints(self, client, test_users):
        """Test CRUD endpoints for callsign mappings"""
        # Use existing test users and authentication from conftest.py
```

#### End-to-End Tests (New marker but existing structure)
**User Workflows** - **New marker in existing test files**:
```python
# Add to existing test files with new @pytest.mark.callsign marker

@pytest.mark.callsign
@pytest.mark.integration
class TestCallsignWorkflows:
    """Test callsign user workflows - follows existing E2E test patterns"""
    
    def test_create_stream_with_callsigns(self, authenticated_client):
        """Test complete stream creation with callsign mapping"""
        # Use existing authenticated_client fixture from conftest.py

    def test_edit_stream_callsigns(self, authenticated_client, test_users):
        """Test editing existing callsign mappings"""
        # Use existing fixtures and test patterns
```

#### Test Fixtures Integration
**Add to `tests/conftest.py`** (existing file):
```python
@pytest.fixture
def test_callsign_mappings(app, db_session, test_streams):
    """Create test callsign mappings - follows existing fixture patterns"""
    mappings = {}
    
    # Create test mappings for existing test streams
    for stream_name, stream in test_streams.items():
        if stream.plugin_type in ['garmin', 'spot', 'traccar']:  # Only tracker plugins
            mapping = CallsignMapping(
                stream_id=stream.id,
                identifier_value=f"TEST_{stream_name.upper()}",
                custom_callsign=f"CALL_{stream_name.upper()}",
                cot_type="a-f-G-U-C"
            )
            db_session.add(mapping)
            mappings[stream_name] = mapping
    
    db_session.commit()
    return mappings

@pytest.fixture  
def test_streams(app, db_session):
    """Create test streams - add to existing fixtures"""
    # Add callsign-related test streams to existing stream fixtures
```

#### Pytest Markers Integration  
**Update `conftest.py` pytest_configure**:
```python
def pytest_configure(config):
    """Configure pytest with custom markers - add to existing markers"""
    config.addinivalue_line("markers", "integration: mark test as integration test")
    config.addinivalue_line("markers", "ldap: mark test as requiring LDAP server")  
    config.addinivalue_line("markers", "oidc: mark test as requiring OIDC provider")
    config.addinivalue_line("markers", "performance: mark test as performance test")
    config.addinivalue_line("markers", "security: mark test as security test")
    config.addinivalue_line("markers", "callsign: mark test as callsign mapping test")  # NEW
    config.addinivalue_line("markers", "database: mark test as requiring specific database")  # NEW
```

### TDD Implementation Phases

#### Phase 1: Database & Models (TDD)
1. **Write failing test** for CallsignMapping model creation
2. **Create minimal model** to pass test
3. **Write failing test** for Stream relationship
4. **Add relationship** to pass test
5. **Write failing test** for unique constraints
6. **Add constraints** to pass test
7. **Refactor** model design while keeping tests green

#### Phase 2: Plugin Interface (TDD)
1. **Write failing test** for plugin field metadata
2. **Implement get_available_fields()** to pass test
3. **Write failing test** for callsign mapping application
4. **Implement apply_callsign_mapping()** to pass test  
5. **Write failing test** for fallback behavior
6. **Implement fallback logic** to pass test
7. **Refactor** plugin interface while keeping tests green

#### Phase 3: Stream Worker Integration (TDD)
1. **Write failing test** for disabled feature (early exit)
2. **Implement early exit logic** to pass test
3. **Write failing test** for enabled callsign mapping
4. **Implement mapping application** to pass test
5. **Write failing test** for per-callsign CoT types  
6. **Implement CoT type overrides** to pass test
7. **Refactor** worker logic while keeping tests green

#### Phase 4: API & Routes (TDD)
1. **Write failing test** for tracker discovery endpoint
2. **Implement minimal endpoint** to pass test
3. **Write failing test** for callsign CRUD operations
4. **Implement CRUD endpoints** to pass test
5. **Write failing test** for error handling
6. **Implement error handling** to pass test
7. **Refactor** API design while keeping tests green

#### Phase 5: UI Integration (TDD)
1. **Write failing test** for checkbox toggle functionality
2. **Implement checkbox behavior** to pass test
3. **Write failing test** for immediate tracker discovery
4. **Implement discovery UI** to pass test
5. **Write failing test** for form submission
6. **Implement form processing** to pass test
7. **Refactor** UI components while keeping tests green

### Test Quality Standards - Integrated with Existing System

**Coverage Requirements** (Building on existing coverage):
- **Unit Tests**: 95%+ code coverage for all new callsign code (adds to existing coverage)
- **Integration Tests**: All database operations and API endpoints tested across all database types  
- **E2E Tests**: All user workflows from spec acceptance criteria using existing test patterns

**Test Data Management** (Using existing fixtures):
- **Existing Fixtures**: Reuse `app`, `db_session`, `client`, `authenticated_client` from conftest.py
- **New Fixtures**: Add `test_callsign_mappings` following existing fixture patterns
- **Database Cleanup**: Use existing database test cleanup patterns
- **Mock Data**: Extend existing mock data for realistic tracker data

**Test Execution Integration**:
- **Existing Commands**: All tests run with existing `pytest` commands
- **Coverage Reports**: Integrate with existing coverage reporting
- **CI/CD Integration**: Use existing GitLab CI test infrastructure  
- **Cross-Database Testing**: Extend existing database test matrix

**Test Organization**:
- **File Structure**: Add to existing test files where possible, minimal new files
- **Naming Conventions**: Follow existing test naming patterns (TestClassName, test_method_name)
- **Markers**: Add `@pytest.mark.callsign` and `@pytest.mark.database` to existing marker system
- **Fixtures**: Extend existing fixtures rather than creating duplicates

**Continuous Integration** (Extends existing CI):
- **Pre-commit**: All callsign tests included in existing pre-commit hook requirements
- **Cross-Database**: Leverage existing database test infrastructure for MySQL, PostgreSQL, SQLite  
- **Performance**: Tests integrated into existing performance test suite
- **Coverage**: Callsign test coverage included in overall project coverage metrics

### TDD Benefits for This Feature

**Design Benefits**:
- **Clean Interfaces**: TDD forces well-defined plugin interfaces
- **Modular Code**: Each component tested independently
- **Clear Contracts**: Tests document expected behavior

**Quality Benefits**:
- **Regression Prevention**: Changes can't break existing functionality  
- **Refactoring Safety**: Tests enable confident code improvements
- **Documentation**: Tests serve as living documentation

**Development Benefits**:
- **Faster Development**: Clear requirements and immediate feedback
- **Reduced Debugging**: Issues caught early in development cycle
- **Confidence**: Comprehensive test coverage ensures reliability

## Technical Debt Elimination

### Removed Complexity
- **Hardcoded field mappings** in `routes/api.py` - replaced with plugin interface calls
- **Complex form JavaScript** - simplified with immediate discovery pattern
- **JSON column encryption** - replaced with dedicated table
- **Mixed implementation patterns** - unified approach using plugin interface

### Code Quality Improvements
- **Consistent plugin interface** - all tracker plugins follow same pattern
- **Separated concerns** - database, UI, and plugin logic cleanly separated
- **Testable components** - each piece can be unit tested independently
- **Clear fallback strategy** - well-defined behavior when features disabled or fail
- **Cross-database compatibility** - single migration works on all supported databases
- **TDD-driven development** - comprehensive test coverage ensures quality and maintainability