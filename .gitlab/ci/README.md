# GitLab CI/CD Modular Configuration

This directory contains modular GitLab CI/CD configuration files organized by pipeline stage for better maintainability and reusability.

## Directory Structure

```
.gitlab/
└── ci/
    ├── validate.yml      # Validation stage jobs (pyproject/version sanity checks)
    ├── test.yml          # Test stage jobs (unit, integration, database compatibility)
    ├── security.yml      # Security stage jobs (SAST, dependency scanning, license scanning)
    ├── build.yml         # Build stage jobs (dev/staging/main container images)
    ├── deploy.yml        # Deploy stage jobs (staging/production container deploys)
    ├── release.yml       # Release stage jobs (tag builds, GHCR/Docker Hub publish)
    └── README.md         # This file
```

## Files Included

### validate.yml
Pre-flight validation jobs that run before test/build stages.

### test.yml
Contains all testing-related jobs:
- **code-quality** - Code formatting, style, and import checks using Black, Flake8, and isort
- **unit-tests** - Unit test suite with coverage reporting using pytest
- **integration-tests-sqlite** - Integration tests with SQLite backend for fast feedback
- **integration-tests-postgresql** - Integration tests with PostgreSQL backend (production-like)
- **integration-tests-mysql** - Integration tests with MySQL/MariaDB backend
- **database-compatibility-tests** - Database configuration switching and precedence tests

All three integration-test jobs install `mosquitto` and `mosquitto-clients` in their `before_script`
so that the outbound MQTT plugin integration tests can start a real broker fixture.

Includes shared templates:
- `.install_packages` - Cross-platform package installation script (includes mosquitto)
- `.postgres_service` - PostgreSQL service configuration
- `.sqlite_service` - SQLite service configuration
- `.mysql_service` - MySQL/MariaDB service configuration

### security.yml
Contains all security-related jobs:
- **bandit-sast** - Static security analysis for Python code vulnerabilities
- **safety-check** - Dependency vulnerability scanning with GitLab Dependency Scanning integration
- **license-scanning** - License compliance checking with GitLab License Scanning integration

Includes shared templates:
- `.install_packages` - Cross-platform package installation script

### build.yml
Container image build jobs for the `develop`, `staging`, and `main` branches. Each job stamps the image with a setuptools-scm pretend version derived from `[tool.trakbridge.release].next` in `pyproject.toml`:

- **develop** → `${NEXT}.dev0+g<short-sha>`
- **staging** → `${NEXT}.rc0+staging.<short-sha>`
- **main** → `${NEXT}` (or `$CI_COMMIT_TAG` on tag pipelines)

Bumping the next-release target is a one-line edit to `pyproject.toml`, reviewed alongside the work that motivates it. Tag builds continue to use `$CI_COMMIT_TAG` directly. Keeping the pretend version aligned with reality is what makes plugin `min_trakbridge_version` gates honest on non-tag builds.

### deploy.yml
Container deploy jobs for the staging and production environments.

### release.yml
Tag-triggered release jobs: multi-arch container image publish to GHCR and Docker Hub, GitLab release creation, changelog surfacing.

## How to Use

### Include in Main .gitlab-ci.yml

The top-level `.gitlab-ci.yml` includes each module directly:

```yaml
include:
  - local: .gitlab/ci/validate.yml
  - local: .gitlab/ci/test.yml
  - local: .gitlab/ci/security.yml
  - local: .gitlab/ci/build.yml
  - local: .gitlab/ci/deploy.yml
  - local: .gitlab/ci/release.yml
```

## Important Notes

### Shared Templates
Both `test.yml` and `security.yml` define the `.install_packages` anchor. When including both files:
- GitLab will use the last definition encountered
- This is safe since the `.install_packages` script is identical in both files
- If you want to avoid duplication, create a separate `templates.yml` file with shared definitions and include it in both test and security files

### Database Service Variables
The database service templates (`.postgres_service`, `.sqlite_service`, `.mysql_service`) automatically set:
- `DB_TYPE` - The type of database (postgresql, sqlite, mysql)
- `DATABASE_URL` - The connection string

Jobs using these templates via `<<: *service_name` inherit these variables.

### Report Formats
All jobs generate GitLab-compatible reports:
- **Code Quality** - `codequality` report format
- **Unit/Integration Tests** - `junit` reports and `coverage_report` (cobertura format)
- **Bandit SAST** - `sast` report format
- **Safety Dependencies** - `dependency_scanning` report format
- **License Scanning** - `license_scanning` report format

These reports integrate directly with GitLab's UI for visualization and tracking.

## Customization Guide

### Adjusting Timeouts
Modify the `timeout` field in any job. Default values are:
- code-quality: 15m
- unit-tests: 20m
- integration tests: 10-15m
- security scans: 10-15m

### Changing Python Version
Update the `PYTHON_VERSION` variable in your main `.gitlab-ci.yml`. All jobs use `${PYTHON_VERSION}` for flexibility.

### Modifying Coverage Threshold
In `unit-tests` job, adjust `COVERAGE_THRESHOLD` variable (default: 20%).

### Adding/Removing Database Tests
- To skip MySQL tests: Remove `integration-tests-mysql` job
- To add new database: Create new job with appropriate service template
- To run only certain databases: Remove unwanted integration test jobs

### Customizing Code Quality Rules
Modify the `code-quality` job to adjust linter configuration:
- Black: `--line-length` parameter
- Flake8: `--max-line-length`, `--extend-ignore`
- isort: Add configuration file or adjust defaults

## Environment Variables Required

### For Security Scans
- `SAFETY_API_KEY` (optional) - PyUp.io API key for Safety premium features

### For Tests
- `SECRET_KEY` - Set per environment (included in jobs)
- `TRAKBRIDGE_ENCRYPTION_KEY` - Set per environment (included in jobs)

### For Docker/Container Registry
- `CI_REGISTRY_USER` - GitLab container registry username
- `CI_REGISTRY_PASSWORD` - GitLab container registry password

## Tags

All jobs are configured to run on `trakbridge-ci` and `trakbridge-cd` tags:
- `trakbridge-ci` - For CI jobs (tests, security scans)
- `trakbridge-cd` - For CD jobs (builds, deployments)

Ensure your GitLab Runner is registered with these tags or update to match your runner configuration.

## Artifacts Retention

- **Test artifacts**: 14 days
- **Security reports**: 1 week
- **Code quality reports**: 1 week

Adjust `expire_in` values if you need longer retention.

## Running Specific Stages

To manually trigger only test or security stages, use GitLab's pipeline UI or API:

```bash
# Run all test jobs
gitlab-runner run --stage test

# Run all security jobs
gitlab-runner run --stage security
```

## Troubleshooting

### Database Connection Issues
If integration tests fail with connection errors:
1. Ensure services are starting properly (check container logs)
2. Verify the wait loops in job scripts (especially MySQL)
3. Check network connectivity between job container and service

### Cache Issues
Jobs use two cache layers:
- `pip-$CI_COMMIT_REF_SLUG-$PYTHON_VERSION` - Python packages
- `python-venv-$CI_COMMIT_REF_SLUG-$PYTHON_VERSION` - Virtual environment

If cache is stale, you can clear it via GitLab UI and re-run.

### Coverage Report Issues
If coverage reports don't appear in MR:
1. Ensure pytest-cov is installed (included in `.[dev]` extras)
2. Check that tests actually run (not skipped)
3. Verify coverage.xml is generated in job artifacts

## Further Reading

- [GitLab CI/CD Documentation](https://docs.gitlab.com/ee/ci/)
- [GitLab Code Quality](https://docs.gitlab.com/ee/ci/testing/code_quality.html)
- [GitLab SAST](https://docs.gitlab.com/ee/user/application_security/sast/)
- [GitLab Dependency Scanning](https://docs.gitlab.com/ee/user/application_security/dependency_scanning/)
- [GitLab License Scanning](https://docs.gitlab.com/ee/user/compliance/license_scanning_of_dependencies.html)
