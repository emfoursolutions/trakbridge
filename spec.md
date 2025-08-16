# TrakBridge CI/CD Staging Enhancement Specification

## Overview

This specification defines the implementation of a production-mirrored staging environment in the TrakBridge GitLab CI/CD pipeline. The staging environment validates all three supported database types (PostgreSQL, MySQL, SQLite) using production-like secrets, configuration, and deployment patterns before tagged releases.

## Architecture

### Current State
- GitLab CI/CD pipeline with validate, test, build, security, deploy stages
- Existing staging job with manual triggers using environment variables
- Production deployment using `docker-compose.yml` with profiles and secrets files
- `setup.sh` script that generates production secrets and database initialization

### Target State
- Enhanced staging job that mirrors production deployment exactly
- Sequential testing of all three database types in a single job
- Production-like secrets management with CI/CD variable injection
- Comprehensive validation including migrations, health checks, and authentication
- Manual trigger on tagged releases only as pre-production validation gate

## Implementation Details

### 1. New Staging Job: `staging-production-mirror`

**Location**: `.gitlab-ci.yml` (replaces existing `deploy-staging`)
**Trigger**: Manual, on tagged releases only (`if: $CI_COMMIT_TAG`)
**Duration**: 90 minutes (extended for comprehensive testing)
**Runner**: `trakbridge-cd` (requires Docker access)

### 2. Production-Like Secrets Setup

**Process**:
1. Execute `scripts/setup.sh --force` to create production directory structure
2. Generate all secrets: `db_password`, `secret_key`, `tb_master_key`, `oidc_client_secret`
3. Inject LDAP password from GitLab CI/CD variable into `secrets/ldap_bind_password`
4. Use Docker secrets mounting identical to production `docker-compose.yml`

**GitLab Variables Required**:
- `LDAP_BIND_PASSWORD`: Real LDAP service account password
- `DOCKERHUB_USERNAME`: For pulling tagged release images
- `DOCKERHUB_TOKEN`: DockerHub authentication

### 3. Sequential Database Testing

**Test Order**: PostgreSQL → MySQL → SQLite

**Per Database Tests**:
1. **Deployment**: Full stack deployment using production `docker-compose.yml` profiles
2. **Migration Testing**: Execute comprehensive migration test suite (`tests/unit/test_migrations.py`)
3. **Health Validation**: Test `/api/health` endpoint and container health status
4. **Database Connectivity**: Verify database connection and basic operations
5. **Authentication Testing**: Test local authentication and LDAP connectivity
6. **API Functionality**: Validate core API endpoints and static assets
7. **Cleanup**: Remove containers and volumes before next database test

### 4. Database-Specific Configuration

#### PostgreSQL
```bash
DB_TYPE=postgresql
DB_HOST=postgres
DB_PORT=5432
COMPOSE_PROFILE=postgres
```

#### MySQL
```bash
DB_TYPE=mysql
DB_HOST=mysql
DB_PORT=3306
COMPOSE_PROFILE=mysql
```

#### SQLite
```bash
DB_TYPE=sqlite
COMPOSE_PROFILE=""  # No external database
```

### 5. Test Script: `scripts/test-database.sh`

**Parameters**: `<db_type> <profile> <image_tag>`
**Functionality**:
- Database-specific deployment with production docker-compose patterns
- Comprehensive test execution with detailed logging
- JSON test reporting for each database
- JUnit XML generation for GitLab integration
- Automatic cleanup between tests

**Test Coverage**:
- Container health validation
- Database migration verification
- Application health endpoint testing
- Database connectivity validation
- Local authentication testing
- LDAP connectivity testing (if enabled)
- Basic API functionality validation

### 6. Comprehensive Reporting

**Artifacts Generated**:
- `staging-test-results.json`: Overall test execution summary
- `staging-deployment-health.json`: Deployment health metrics
- `test-reports/postgresql-test-report.json`: PostgreSQL test details
- `test-reports/mysql-test-report.json`: MySQL test details
- `test-reports/sqlite-test-report.json`: SQLite test details
- `test-reports/junit-*.xml`: JUnit reports for GitLab integration
- `logs/`: Application and test logs

**Report Structure**:
```json
{
  "test_run": {
    "timestamp": "2025-01-01T12:00:00Z",
    "release_tag": "v1.0.0",
    "total_tests": 3,
    "passed": 3,
    "failed": 0,
    "status": "passed"
  },
  "database_tests": [
    {
      "database": "postgresql",
      "status": "passed",
      "timestamp": "2025-01-01T12:15:00Z"
    }
  ]
}
```

### 7. Environment Configuration

**Production-Like Settings**:
- LDAP enabled with real server connection
- Production-like timeouts and security settings
- Full secret file mounting
- Production Docker image from DockerHub
- Real authentication provider testing

**Environment Variables**:
```bash
LDAP_ENABLED=true
LDAP_SERVER=ldap://your-ad-server.company.com
LDAP_USE_TLS=true
LDAP_VALIDATE_CERT=true
SESSION_SECURE_COOKIES=true
FLASK_ENV=testing  # For enhanced error reporting
```

### 8. Failure Handling

**Failure Scenarios**:
- Individual database test failure stops overall pipeline
- Detailed error logging with container logs
- Test artifacts preserved for debugging
- Clear pass/fail status in GitLab UI

**Exit Conditions**:
- Any database test failure: Pipeline fails with detailed report
- All tests pass: Pipeline succeeds with validation confirmation
- Missing dependencies: Early failure with clear error message

### 9. Integration Points

**Pipeline Dependencies**:
- Requires successful `build-tagged-image-shell` job
- Uses tagged Docker images from DockerHub
- Integrates with GitLab security scanning results

**GitLab Integration**:
- Manual approval gate for production releases
- JUnit test reporting in merge request UI
- Artifact preservation for 1 month
- Environment tracking for staging validation

## Deployment Process

### 1. Pre-Release Workflow
1. Developer creates tagged release
2. Pipeline builds and pushes multiplatform images
3. Manual trigger of `staging-production-mirror` job
4. Comprehensive validation of all database types
5. Review validation results before production deployment

### 2. Validation Gates
- All three database types must pass validation
- Migration tests must succeed across all databases
- LDAP connectivity must be verified
- Health checks must pass for all configurations

### 3. Production Readiness Criteria
- ✅ PostgreSQL deployment and functionality validated
- ✅ MySQL deployment and functionality validated  
- ✅ SQLite deployment and functionality validated
- ✅ All database migrations tested and verified
- ✅ LDAP authentication connectivity confirmed
- ✅ Production secrets and configuration validated

## Benefits

### 1. Risk Reduction
- Validates all supported database configurations before production
- Tests production-like secrets and authentication
- Verifies migration compatibility across database types
- Confirms LDAP connectivity with real authentication server

### 2. Quality Assurance
- Comprehensive automated testing of full stack
- Production-identical deployment patterns
- Real-world authentication and authorization testing
- Complete validation of release artifacts

### 3. Operational Confidence
- Manual approval gate provides control over production releases
- Detailed test reporting for troubleshooting
- Production-ready validation of configuration and secrets
- Clear pass/fail criteria for release decisions

## Technical Requirements

### GitLab Runner Requirements
- Docker daemon access for container operations
- Sufficient resources for sequential database testing
- Network access to LDAP server for authentication testing
- Internet access for DockerHub image pulling

### GitLab Configuration Requirements
- CI/CD variables for LDAP password and DockerHub credentials
- Manual approval permissions for staging environment
- Artifact storage for test reports and logs
- JUnit test result integration

### Infrastructure Requirements
- Available ports for database services (5432, 3306)
- Disk space for multiple database volumes
- Memory for running multiple container stacks sequentially
- Network connectivity to external authentication services

## Success Metrics

### 1. Validation Coverage
- 100% database type coverage (PostgreSQL, MySQL, SQLite)
- Complete migration test execution
- Full authentication stack validation
- Production configuration verification

### 2. Reliability
- Consistent test execution across database types
- Accurate pass/fail determination
- Comprehensive error reporting and debugging
- Reliable cleanup between test phases

### 3. Integration
- Seamless GitLab CI/CD integration
- Clear test result reporting
- Effective manual approval workflow
- Production deployment confidence

This specification provides a comprehensive foundation for implementing production-mirrored staging validation that ensures release quality and reduces production deployment risk.