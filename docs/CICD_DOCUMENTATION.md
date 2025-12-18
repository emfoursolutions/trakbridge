# TrakBridge CI/CD Pipeline Documentation

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Pipeline Overview](#pipeline-overview)
3. [Migration Guide](#migration-guide)
4. [Infrastructure Architecture](#infrastructure-architecture)
5. [Build Stage Configuration](#build-stage-configuration)
6. [Deployment Configuration](#deployment-configuration)
7. [Release Management](#release-management)
8. [Testing Strategy](#testing-strategy)
9. [Security Scanning](#security-scanning)
10. [Troubleshooting Guide](#troubleshooting-guide)
11. [Reference Information](#reference-information)

---

## Executive Summary

The TrakBridge GitLab CI/CD pipeline has been fully migrated to a modular architecture across six implementation phases. This migration provides improved maintainability, multi-database testing capabilities, and automated deployment workflows with comprehensive security scanning.

### Key Achievements

- Modular pipeline structure with separate configuration files per stage
- Traefik reverse proxy integration with automatic SSL/TLS certificates
- Multi-database testing support (PostgreSQL, MySQL, SQLite)
- Automated SSH-based deployments to development, staging, and production environments
- Multi-platform Docker image builds for production releases
- Public distribution via DockerHub

### Pipeline Stages

1. **Validate** - Configuration validation (YAML, requirements, pyproject)
2. **Test** - Code quality, unit tests, integration tests
3. **Security** - Static analysis, dependency scanning, licence compliance
4. **Build** - Docker image builds for development, staging, and production
5. **Deploy** - Automated deployments with health check validation
6. **Release** - Public distribution to DockerHub

---

## Pipeline Overview

### File Organisation

```
.gitlab-ci.yml                      # Main pipeline configuration (88 lines)
.gitlab/ci/
├── validate.yml                    # Validation jobs (136 lines)
├── test.yml                        # Test jobs (416 lines)
├── security.yml                    # Security jobs (368 lines)
├── build.yml                       # Build jobs (246 lines)
├── deploy.yml                      # Deployment jobs (357 lines)
└── release.yml                     # Release jobs (18 lines)
```

### Branch Strategy

| Branch | Build Trigger | Deploy Trigger | Image Tags |
|--------|---------------|----------------|------------|
| develop | Automatic | Automatic (PostgreSQL) | dev-{sha}, dev-latest |
| staging | Automatic | Automatic | staging-{sha}, staging-latest |
| main | Automatic | Manual | prod-{sha}, prod-latest |
| v*.*.* (tags) | Automatic | Manual | {tag}, latest |

### Environment Matrix

| Environment | URL | Database | Trigger | Purpose |
|-------------|-----|----------|---------|---------|
| Development (PostgreSQL) | https://tb-dev.emfour.net | PostgreSQL | Auto | Primary development |
| Development (MySQL) | https://tb-dev-mysql.emfour.net | MySQL | Manual | Migration testing |
| Development (SQLite) | https://tb-dev-sqlite.emfour.net | SQLite | Manual | Migration testing |
| Staging | https://tb-staging.emfour.net | PostgreSQL | Auto | UAT validation |
| Production | https://tb.emfour.net | PostgreSQL | Manual | Production deployment |

---

## Migration Guide

### Overview

The migration transforms a monolithic 1,269-line `.gitlab-ci.yml` file into a modular structure with six separate configuration files, improving organisation and maintainability.

### Migration Benefits

1. **Better Organisation** - Each stage has its own file, easier to navigate
2. **Easier Maintenance** - Find and update related jobs in one place
3. **Reusability** - Share templates across different projects
4. **Cleaner Git Diffs** - Changes to one stage don't affect others
5. **Scalability** - Easy to add new stages or jobs without cluttering the main file
6. **Team Collaboration** - Different teams can own different CI files

### Migration Steps

#### Step 1: Review Modular Files

The following files have been created in `.gitlab/ci/`:

- **validate.yml** - YAML syntax validation, requirements validation, pyproject validation
- **test.yml** - Code quality checks, unit tests, integration tests (PostgreSQL, MySQL, SQLite)
- **security.yml** - Bandit SAST, Safety dependency scanning, licence scanning
- **build.yml** - Docker image builds for development, staging, production
- **deploy.yml** - SSH-based deployments with health checks
- **release.yml** - DockerHub publication

#### Step 2: Update Main Pipeline

The new `.gitlab-ci.yml` includes modular files:

```yaml
stages:
  - validate
  - test
  - security
  - build
  - deploy-dev
  - deploy-staging
  - deploy-prod
  - release

variables:
  PYTHON_VERSION: "3.12"
  DOCKER_DRIVER: overlay2
  DOCKER_TLS_CERTDIR: ""

include:
  - local: .gitlab/ci/validate.yml
  - local: .gitlab/ci/test.yml
  - local: .gitlab/ci/security.yml
  - local: .gitlab/ci/build.yml
  - local: .gitlab/ci/deploy.yml
  - local: .gitlab/ci/release.yml
```

#### Step 3: Verify Configuration

Before committing, validate the configuration:

**Using GitLab CI Lint:**
1. Navigate to your project
2. Go to CI/CD > Pipelines > CI Lint
3. Paste your configuration to validate

**Using GitLab CLI (if available):**
```bash
gitlab-runner verify --output format=json
```

#### Step 4: Test on Feature Branch

```bash
# Create test branch
git checkout -b test/modular-ci

# Commit changes
git add .gitlab-ci.yml .gitlab/ci/
git commit -m "feat: implement modular CI/CD pipeline"

# Push and monitor
git push origin test/modular-ci
```

Monitor the pipeline to ensure all stages execute correctly.

#### Step 5: Rollback Plan

If issues occur, the rollback is straightforward:

```bash
# Restore original pipeline
cp .gitlab-ci.yml.backup .gitlab-ci.yml

# Commit rollback
git add .gitlab-ci.yml
git commit -m "revert: rollback to original CI pipeline"
git push origin develop
```

---

## Infrastructure Architecture

### Deployment Server

**Host:** dep-en-dev-01.emfour.net

**Directory Structure:**
```
/opt/dev/
├── tb-dev/                         # Development (PostgreSQL)
│   ├── logs/
│   ├── data/
│   ├── secrets/
│   ├── backups/
│   └── config/
├── tb-dev-mysql/                   # Development (MySQL)
│   ├── logs/
│   ├── data/
│   ├── secrets/
│   ├── backups/
│   └── config/
├── tb-dev-sqlite/                  # Development (SQLite)
│   ├── logs/
│   ├── data/
│   ├── secrets/
│   ├── backups/
│   └── config/
└── tb-staging/                     # Staging
    ├── logs/
    ├── data/
    ├── secrets/
    ├── backups/
    └── config/

/opt/prod/
└── trakbridge/                     # Production
    ├── logs/
    ├── data/
    ├── secrets/
    ├── backups/
    └── config/
```

### Network Architecture

**Traefik Reverse Proxy:**
- External network: `frontend`
- Automatic SSL/TLS via Let's Encrypt
- Domain-based routing
- Certificate resolver: `letsencrypt`
- HTTPS entrypoint: `websecure` (port 443)

**Application Networks:**
- Internal application network per environment
- Connection to Traefik frontend network
- No direct port exposure

### DNS Configuration

Ensure the following DNS records point to dep-en-dev-01.emfour.net:

- tb-dev.emfour.net
- tb-dev-mysql.emfour.net
- tb-dev-sqlite.emfour.net
- tb-staging.emfour.net
- tb.emfour.net

---

## Build Stage Configuration

### Build Jobs

#### build-dev (Development Builds)

**Trigger:** Automatic on develop branch
**Runner:** shell executor
**Timeout:** 45 minutes
**Platform:** linux/amd64

**Image Tags:**
- `{CI_REGISTRY_IMAGE}:dev-{CI_COMMIT_SHORT_SHA}`
- `{CI_REGISTRY_IMAGE}:dev-latest`

**Version:** `0.1.0.dev0+g{CI_COMMIT_SHORT_SHA}`

**Purpose:** Fast development builds for testing on the develop branch.

#### build-staging (Staging Builds)

**Trigger:** Automatic on staging branch
**Runner:** shell executor
**Timeout:** 45 minutes
**Platform:** linux/amd64

**Image Tags:**
- `{CI_REGISTRY_IMAGE}:staging-{CI_COMMIT_SHORT_SHA}`
- `{CI_REGISTRY_IMAGE}:staging-latest`

**Version:** `0.1.0.dev0+staging.{CI_COMMIT_SHORT_SHA}`

**Purpose:** Staging builds for UAT and final validation before production.

#### build-prod (Production Builds)

**Trigger:** Automatic on main branch OR git tags
**Runner:** shell executor
**Timeout:** 120 minutes (for multi-platform builds)

**Platforms:**
- Main branch: linux/amd64
- Git tags: linux/amd64, linux/arm64

**Image Tags:**
- Main branch:
  - `{CI_REGISTRY_IMAGE}:prod-{CI_COMMIT_SHORT_SHA}`
  - `{CI_REGISTRY_IMAGE}:prod-latest`
- Git tags:
  - `{CI_REGISTRY_IMAGE}:{CI_COMMIT_TAG}`
  - `{CI_REGISTRY_IMAGE}:latest`

**Version:**
- Main branch: `0.1.0.dev0+prod.{CI_COMMIT_SHORT_SHA}`
- Git tags: `{CI_COMMIT_TAG}`

**Purpose:** Production-ready builds with multi-platform support for releases.

### Docker Build Configuration

**Environment Variables:**
- `DOCKER_BUILDKIT=1` - Improved build performance
- `SETUPTOOLS_SCM_PRETEND_VERSION` - Python version override
- `DOCKER_DRIVER: overlay2` - Storage driver
- `DOCKER_TLS_CERTDIR: ""` - Disable TLS (uses host daemon)

**Build Arguments:**
- `--target=production` - Build production stage
- `--platform` - Architecture specification
- OCI labels for metadata

**Multi-Platform Builds:**
- Uses Docker Buildx
- Platforms: linux/amd64, linux/arm64
- Applied only to git tags
- Requires `--push` flag with buildx

### Runner Requirements

**Software:**
- Docker 20.10+
- Docker Buildx support
- Shell executor access

**Permissions:**
- Access to host Docker daemon
- GitLab Container Registry credentials (auto-provided)

---

## Deployment Configuration

### SSH Configuration

**Required GitLab Variables:**

| Variable | Type | Description | Protected | Masked |
|----------|------|-------------|-----------|--------|
| DEPLOY_SSH_KEY | Variable | Base64-encoded SSH private key | Yes | Yes |
| DEPLOY_HOST | Variable | dep-en-dev-01.emfour.net | No | No |
| DEPLOY_USER | Variable | gitlab-deploy | No | No |

**SSH Key Generation:**

```bash
# Generate SSH key
ssh-keygen -t ed25519 -C "gitlab-ci-trakbridge" -f trakbridge_deploy_key

# Add to deployment server
ssh-copy-id -i trakbridge_deploy_key.pub gitlab-deploy@dep-en-dev-01.emfour.net

# Base64 encode for GitLab (macOS)
base64 -i trakbridge_deploy_key -o trakbridge_deploy_key.b64

# Base64 encode for GitLab (Linux)
base64 -w 0 trakbridge_deploy_key > trakbridge_deploy_key.b64

# Add contents of .b64 file to GitLab variable DEPLOY_SSH_KEY
```

### Deployment Jobs

#### deploy-dev-postgres (Automatic)

**Domain:** https://tb-dev.emfour.net
**Path:** /opt/dev/tb-dev
**Database:** PostgreSQL
**Trigger:** Automatic on develop branch
**Compose File:** docker-compose-dev.yml
**Profile:** postgres

**Purpose:** Primary development environment with automatic deployment.

#### deploy-dev-mysql (Manual)

**Domain:** https://tb-dev-mysql.emfour.net
**Path:** /opt/dev/tb-dev-mysql
**Database:** MySQL/MariaDB
**Trigger:** Manual on develop branch
**Compose File:** docker-compose-dev.yml
**Profile:** mysql

**Purpose:** MySQL migration testing environment.

#### deploy-dev-sqlite (Manual)

**Domain:** https://tb-dev-sqlite.emfour.net
**Path:** /opt/dev/tb-dev-sqlite
**Database:** SQLite
**Trigger:** Manual on develop branch
**Compose File:** docker-compose-dev.yml
**Database Type:** sqlite (via environment variable)

**Purpose:** SQLite migration testing environment.

#### deploy-staging (Automatic)

**Domain:** https://tb-staging.emfour.net
**Path:** /opt/dev/tb-staging
**Database:** PostgreSQL
**Trigger:** Automatic on staging branch
**Compose File:** docker-compose.staging.yml
**Profile:** postgres

**Purpose:** UAT and final validation before production.

#### deploy-prod (Manual)

**Domain:** https://tb.emfour.net
**Path:** /opt/prod/trakbridge
**Database:** PostgreSQL
**Trigger:** Manual on main branch or git tags
**Compose File:** docker-compose.yml
**Profile:** postgres

**Purpose:** Production deployment with strict validation.

**Special Features:**
- Manual trigger only
- Strict health check (fails on error)
- Dynamic image tag detection (tag vs main branch)

### Health Check Configuration

**Endpoint:** `https://{domain}/api/health`

**Retry Logic:**
- Initial delay: 30 seconds
- Retry attempts: 5
- Delay between retries: 10 seconds
- Total timeout: ~80 seconds

**Behaviour:**
- Development/Staging: Logs warnings, continues
- Production: Fails pipeline on health check failure

### Multi-Database Testing Workflow

**Purpose:** Catch database-specific migration bugs before production.

**Workflow:**

1. **Develop feature** on feature branch
2. **Merge to develop** - Auto-deploys PostgreSQL
3. **Test on PostgreSQL** at tb-dev.emfour.net
4. **Manual MySQL test:**
   - Click "Play" on deploy-dev-mysql
   - Test at tb-dev-mysql.emfour.net
   - Verify migrations work
   - Check for MySQL-specific issues
5. **Manual SQLite test:**
   - Click "Play" on deploy-dev-sqlite
   - Test at tb-dev-sqlite.emfour.net
   - Verify migrations work
   - Check for SQLite limitations
6. **Cleanup:**
   - Click "Play" on stop-dev-mysql
   - Click "Play" on stop-dev-sqlite
7. **Merge to staging** if all tests pass

**Benefits:**
- Same image tested across all three databases
- No code changes needed (docker-compose profiles)
- On-demand - no wasted resources
- Catches bugs before staging/production
- Automatic SSL/TLS via Traefik

### Cleanup Jobs

#### stop-dev-mysql

**Action:** Stops and removes MySQL testing environment
**Command:** `docker-compose --profile mysql down -v`
**Trigger:** Manual

**Purpose:** Clean up temporary MySQL testing environment and volumes.

#### stop-dev-sqlite

**Action:** Stops and removes SQLite testing environment
**Command:** `docker-compose down -v` (with DB_TYPE=sqlite)
**Trigger:** Manual

**Purpose:** Clean up temporary SQLite testing environment and volumes.

---

## Release Management

### DockerHub Publication

**Public Repository:** https://hub.docker.com/r/emfoursolutions/trakbridge

**Required GitLab Variables:**

| Variable | Type | Description | Protected | Masked |
|----------|------|-------------|-----------|--------|
| DOCKERHUB_USERNAME | Variable | DockerHub username | Yes | No |
| DOCKERHUB_TOKEN | Variable | DockerHub access token | Yes | Yes |

**Creating DockerHub Access Token:**

1. Log in to DockerHub: https://hub.docker.com
2. Go to Account Settings > Security > Access Tokens
3. Create New Access Token:
   - Description: GitLab CI - TrakBridge
   - Permissions: Read, Write, Delete
4. Copy the token (shown once)
5. Add to GitLab:
   - Settings > CI/CD > Variables
   - Key: DOCKERHUB_TOKEN
   - Value: [paste token]
   - Protected: Yes
   - Masked: Yes

### Release Job

#### release-dockerhub (Manual)

**Trigger:** Manual after successful deploy-prod
**Runner:** shell executor
**Timeout:** 30 minutes
**Dependency:** Requires deploy-prod to succeed

**Workflow:**

1. Pull image from GitLab Container Registry
2. Re-tag for DockerHub (emfoursolutions/trakbridge)
3. Push to DockerHub with version tag and latest tag
4. Verify publication
5. Clean up local images

**Version Handling:**

- Git tags: Publishes as exact version (e.g., v1.0.0)
- Main branch: Publishes as timestamped version (e.g., main-20251213-2030)
- Always updates latest tag

**Published Image Tags:**

| Tag Type | Format | Example | Platforms | Description |
|----------|--------|---------|-----------|-------------|
| Version | v{major}.{minor}.{patch} | v1.0.0 | amd64, arm64 | Official releases |
| Latest | latest | latest | amd64, arm64 | Most recent release |
| Main | main-{timestamp} | main-20251213-2030 | amd64 | Main branch builds |

**Pull Commands:**

```bash
# Latest release
docker pull emfoursolutions/trakbridge:latest

# Specific version
docker pull emfoursolutions/trakbridge:v1.0.0

# Main branch build
docker pull emfoursolutions/trakbridge:main-20251213-2030
```

### Release Process

**For Tagged Releases (Recommended):**

```bash
# Step 1: Create and push git tag
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin v1.0.0

# Step 2: Monitor pipeline (build-prod takes ~120 min for multi-platform)

# Step 3: Click "Play" on deploy-prod job

# Step 4: Verify production deployment at https://tb.emfour.net

# Step 5: Click "Play" on release-dockerhub job

# Step 6: Verify publication at https://hub.docker.com/r/emfoursolutions/trakbridge/tags
```

**For Main Branch Releases:**

```bash
# Step 1: Merge to main
git checkout main
git merge staging
git push origin main

# Step 2: Monitor pipeline (build-prod takes ~45 min for single platform)

# Step 3: Click "Play" on deploy-prod job

# Step 4: Verify production deployment

# Step 5: Click "Play" on release-dockerhub job
# Image published with timestamp: main-YYYYMMDD-HHMMSS
```

---

## Testing Strategy

### Validation Stage

Three validation jobs ensure configuration integrity:

#### validate-yaml

**Purpose:** Validates all YAML configuration files
**Tools:** Python PyYAML
**Files Checked:**
- .gitlab-ci.yml
- All files in .gitlab/ci/
- docker-compose files

**Trigger:** All branches, merge requests, tags

#### validate-requirements

**Purpose:** Validates Python requirements files
**Checks:**
- requirements.txt syntax
- requirements-dev.txt syntax
- No unpinned versions
- No conflicting dependencies

**Trigger:** All branches, merge requests, tags

#### validate-pyproject

**Purpose:** Validates pyproject.toml configuration
**Checks:**
- TOML syntax
- Project metadata
- Build system requirements
- Tool configurations

**Trigger:** All branches, merge requests, tags

### Test Stage

Six test jobs provide comprehensive code coverage:

#### code-quality

**Purpose:** Code formatting, style, and import checks
**Tools:** Black, Flake8, isort
**Timeout:** 15 minutes

**Checks:**
- Black code formatting
- Flake8 style compliance
- isort import organisation

**Report:** GitLab Code Quality report (JSON)
**Artifacts:** Code quality report, tool outputs
**Trigger:** All branches, merge requests, tags

#### unit-tests

**Purpose:** Unit test suite with coverage reporting
**Tools:** pytest, pytest-cov
**Database:** SQLite (fast unit tests)
**Timeout:** 20 minutes
**Coverage Threshold:** 20%

**Report:** JUnit test results, Cobertura coverage report
**Artifacts:** HTML coverage report, test results
**Trigger:** All branches, merge requests, tags

#### integration-tests-sqlite

**Purpose:** Integration tests against SQLite
**Database:** SQLite (file-based)
**Timeout:** 10 minutes

**Features:**
- Fast feedback
- No external database service required
- Excludes MySQL-specific tests

**Report:** JUnit test results
**Trigger:** All branches, merge requests, tags

#### integration-tests-postgresql

**Purpose:** Integration tests against PostgreSQL
**Database:** PostgreSQL 17 Alpine
**Service:** postgres:17-alpine
**Timeout:** 15 minutes

**Configuration:**
- Database: test_db
- User: test_user
- Password: test_password
- Host: postgres
- Port: 5432

**Report:** JUnit test results
**Trigger:** All branches, merge requests, tags

#### integration-tests-mysql

**Purpose:** Integration tests against MySQL/MariaDB
**Database:** MariaDB 11.8
**Service:** mariadb:11.8
**Timeout:** 15 minutes

**Configuration:**
- Database: test_db
- User: test_user
- Password: test_password
- Host: mariadb
- Port: 3306

**Features:**
- Waits for database readiness
- Tests MySQL-specific functionality
- Verifies MySQL compatibility

**Report:** JUnit test results
**Trigger:** All branches, merge requests, tags

#### database-compatibility-tests

**Purpose:** Tests dynamic database configuration switching
**Timeout:** 15 minutes

**Features:**
- No predefined database configuration
- Tests control database selection
- Verifies configuration precedence rules
- Tests database switching logic

**Report:** JUnit test results
**Trigger:** All branches, merge requests, tags

### Test Templates

Four reusable templates support test jobs:

#### .install_packages

**Purpose:** Cross-platform package installation
**Supported:** apt-get (Debian/Ubuntu), dnf (Rocky/Fedora), yum (RHEL/CentOS)

**Usage:** Referenced by all test and security jobs

#### .postgres_service

**Configuration:**
- Service: postgres:17-alpine
- Alias: postgres
- Database variables configured
- DATABASE_URL provided

#### .sqlite_service

**Configuration:**
- No service needed (file-based)
- DB_TYPE: sqlite

#### .mysql_service

**Configuration:**
- Service: mariadb:11.8
- Alias: mariadb
- Database variables configured
- DATABASE_URL provided

---

## Security Scanning

### Security Stage

Three security jobs provide comprehensive scanning:

#### bandit-sast

**Purpose:** Python static security analysis
**Tool:** Bandit
**Timeout:** 15 minutes

**Scanned Directories:**
- app.py
- services/
- plugins/
- routes/
- models/
- config/

**Report:** GitLab SAST report (JSON)
**Trigger:** All branches, merge requests, tags

#### safety-check

**Purpose:** Dependency vulnerability scanning
**Tool:** Safety
**Timeout:** 10 minutes

**Features:**
- Scans requirements.txt
- Checks known vulnerabilities
- Converts to GitLab Dependency Scanning format
- Optional SAFETY_API_KEY support

**Report:** GitLab Dependency Scanning report (JSON)
**Artifacts:** Safety report, GitLab report
**Trigger:** All branches, merge requests, tags

#### licence-scanning

**Purpose:** Licence compliance checking
**Tool:** pip-licences
**Timeout:** 10 minutes

**Features:**
- Scans all dependencies
- Classifies licences (allowed/denied/unclassified)
- Identifies GPL/AGPL violations
- Generates GitLab Licence Scanning report

**Licence Classification:**
- Allowed: MIT, Apache 2.0, BSD variants
- Denied: GPL, AGPL, LGPL
- Unclassified: Unknown or other licences

**Report:** GitLab Licence Scanning report (JSON)
**Trigger:** All branches, merge requests, tags

### Security Best Practises

**SAST Coverage:**
- Python code analysis with Bandit
- Custom rule support
- Integrated with GitLab Security Dashboard

**Dependency Management:**
- Automated vulnerability scanning
- Version-specific vulnerability detection
- Remediation suggestions

**Licence Compliance:**
- Automated licence detection
- Policy enforcement (GPL/AGPL warnings)
- Dependency tracking

---

## Troubleshooting Guide

### Build Issues

#### Cannot Connect to Docker Daemon

**Symptoms:** "Cannot connect to the Docker daemon"

**Solutions:**
1. Verify runner has shell tag
2. Check Docker access on runner machine:
   ```bash
   docker ps
   ```
3. Verify Docker daemon is running
4. Check runner configuration for Docker socket access

#### Multi-Platform Build Hangs

**Symptoms:** Build timeout during multi-platform compilation

**Solutions:**
1. Verify timeout is set to 120 minutes for git tags
2. Check Buildx configuration:
   ```bash
   docker buildx ls
   docker buildx inspect multiarch
   ```
3. Ensure QEMU is installed for cross-platform builds

#### Images Not Appearing in Registry

**Symptoms:** Built images not visible in GitLab Container Registry

**Solutions:**
1. Check registry authentication:
   ```bash
   echo "$CI_REGISTRY_PASSWORD" | docker login -u "$CI_REGISTRY_USER" --password-stdin "$CI_REGISTRY"
   ```
2. Verify CI_REGISTRY_IMAGE variable is correct
3. Check push command succeeded in build logs
4. Verify registry permissions in project settings

#### Wrong Version in Image

**Symptoms:** Image contains incorrect version string

**Solutions:**
1. Check SETUPTOOLS_SCM_PRETEND_VERSION in build logs:
   ```bash
   grep "SETUPTOOLS_SCM_PRETEND_VERSION" build.log
   ```
2. Verify git tag format matches v*.*.* pattern
3. Ensure setuptools-scm is installed in build environment

### Deployment Issues

#### SSH Connection Fails

**Symptoms:** "Permission denied" or "Connection refused"

**Solutions:**
1. Verify DEPLOY_SSH_KEY is correctly base64-encoded
2. Test SSH manually:
   ```bash
   ssh gitlab-deploy@dep-en-dev-01.emfour.net
   ```
3. Check SSH key in authorized_keys on server
4. Confirm DEPLOY_USER and DEPLOY_HOST variables are correct
5. Verify firewall allows SSH (port 22)

#### Health Check Fails

**Symptoms:** "Health check failed" in deployment logs

**Solutions:**
1. Check application logs:
   ```bash
   ssh gitlab-deploy@dep-en-dev-01.emfour.net "cd /opt/dev/tb-dev && docker-compose logs"
   ```
2. Verify Traefik is running:
   ```bash
   docker ps | grep traefik
   ```
3. Check DNS resolution:
   ```bash
   nslookup tb-dev.emfour.net
   ```
4. Verify frontend network exists:
   ```bash
   docker network ls | grep frontend
   ```
5. Test health endpoint manually:
   ```bash
   curl -I https://tb-dev.emfour.net/api/health
   ```

#### Docker Compose Fails

**Symptoms:** "docker-compose command not found" or compose errors

**Solutions:**
1. Ensure docker-compose is installed on deployment server:
   ```bash
   docker-compose --version
   ```
2. Validate docker-compose file syntax locally
3. Verify secrets exist in deployment path:
   ```bash
   ls -la /opt/dev/tb-dev/secrets/
   ```
4. Check database profile is valid
5. Review compose file for environment variable issues

#### Image Pull Fails

**Symptoms:** "Error pulling image" or authentication errors

**Solutions:**
1. Verify image was built successfully in build stage
2. Check GitLab Container Registry access
3. Test docker login on deployment server:
   ```bash
   echo "$CI_REGISTRY_PASSWORD" | docker login -u "$CI_REGISTRY_USER" --password-stdin "$CI_REGISTRY"
   ```
4. Confirm image tag exists in registry
5. Verify network connectivity to registry

### Release Issues

#### DockerHub Authentication Fails

**Symptoms:** "Error logging in to DockerHub"

**Solutions:**
1. Verify DOCKERHUB_USERNAME is correct
2. Regenerate DOCKERHUB_TOKEN in DockerHub
3. Ensure token has Read/Write/Delete permissions
4. Check token hasn't expired
5. Verify token is correctly masked in GitLab

#### DockerHub Push Fails

**Symptoms:** "Failed to push version tag to DockerHub"

**Solutions:**
1. Verify repository exists on DockerHub
2. Check DockerHub account has push permissions
3. Ensure repository is public or token has access
4. Test manual push from runner:
   ```bash
   docker push emfoursolutions/trakbridge:test
   ```
5. Check for network connectivity issues

#### Images Don't Appear on DockerHub

**Symptoms:** "Could not verify version tag"

**Solutions:**
1. Wait a few minutes (DockerHub indexing delay)
2. Check DockerHub repository manually
3. Verify push commands succeeded in logs
4. Check repository visibility settings
5. Refresh browser cache when viewing DockerHub

### Test Issues

#### Code Quality Failures

**Symptoms:** Code quality job reports issues but passes

**Solutions:**
1. Review gl-code-quality-report.json artefact
2. Apply Black formatting:
   ```bash
   black .
   ```
3. Fix Flake8 issues manually
4. Run isort:
   ```bash
   isort .
   ```
5. Commit formatting changes

#### Integration Test Database Connection Fails

**Symptoms:** "Could not connect to database" in integration tests

**Solutions:**
1. Verify service is running (check job logs)
2. Wait longer for database initialisation
3. Check service alias matches database host
4. Verify database credentials match service configuration
5. Review service container logs in job output

#### Coverage Threshold Not Met

**Symptoms:** "Coverage failed: {percentage}% < {threshold}%"

**Solutions:**
1. Add tests for uncovered code
2. Adjust COVERAGE_THRESHOLD variable if threshold is too high
3. Review coverage report in htmlcov/ artefact
4. Identify critical untested code paths
5. Consider excluding non-critical files from coverage

---

## Reference Information

### GitLab Variables Reference

#### Required Variables (Manual Configuration)

| Variable | Type | Value | Protected | Masked | Purpose |
|----------|------|-------|-----------|--------|---------|
| DEPLOY_SSH_KEY | Variable | Base64-encoded SSH key | Yes | Yes | SSH deployment authentication |
| DEPLOY_HOST | Variable | dep-en-dev-01.emfour.net | No | No | Deployment server hostname |
| DEPLOY_USER | Variable | gitlab-deploy | No | No | Deployment server username |
| DOCKERHUB_USERNAME | Variable | emfoursolutions | Yes | No | DockerHub username |
| DOCKERHUB_TOKEN | Variable | [token] | Yes | Yes | DockerHub access token |

#### Optional Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| PYTHON_VERSION | 3.12 | Python version for all jobs |
| COVERAGE_THRESHOLD | 20 | Minimum coverage percentage |
| SAFETY_API_KEY | (none) | Safety API key for enhanced scanning |

#### Auto-Provided Variables (GitLab)

| Variable | Description |
|----------|-------------|
| CI_REGISTRY_IMAGE | Full image path in GitLab registry |
| CI_REGISTRY_USER | GitLab registry username |
| CI_REGISTRY_PASSWORD | GitLab registry password |
| CI_COMMIT_BRANCH | Current branch name |
| CI_COMMIT_TAG | Git tag (if present) |
| CI_COMMIT_SHA | Full commit SHA |
| CI_COMMIT_SHORT_SHA | Short commit SHA |
| CI_PROJECT_URL | Project URL |

### Server Setup Commands

#### Initial Server Configuration

```bash
# On dep-en-dev-01.emfour.net

# Create deployment directories
sudo mkdir -p /opt/dev/tb-dev/{logs,data,secrets,backups,config}
sudo mkdir -p /opt/dev/tb-dev-mysql/{logs,data,secrets,backups,config}
sudo mkdir -p /opt/dev/tb-dev-sqlite/{logs,data,secrets,backups,config}
sudo mkdir -p /opt/dev/tb-staging/{logs,data,secrets,backups,config}
sudo mkdir -p /opt/prod/trakbridge/{logs,data,secrets,backups,config}

# Set ownership
sudo chown -R gitlab-deploy:gitlab-deploy /opt/dev /opt/prod

# Create Traefik network
docker network create frontend

# Setup secrets (development example)
cd /opt/dev/tb-dev/secrets
openssl rand -hex 32 > secret_key
openssl rand -hex 32 > tb_master_key
echo "your-db-password" > db_password
echo "your-ldap-password" > ldap_bind_password
echo "your-oidc-secret" > oidc_client_secret
chmod 600 secrets/*

# Copy secrets to other environments
cp -r /opt/dev/tb-dev/secrets/* /opt/dev/tb-dev-mysql/secrets/
cp -r /opt/dev/tb-dev/secrets/* /opt/dev/tb-dev-sqlite/secrets/
cp -r /opt/dev/tb-dev/secrets/* /opt/dev/tb-staging/secrets/

# Setup production secrets separately with production credentials
```

#### Deployment Verification

```bash
# Check running containers
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# View logs
docker-compose -f /opt/dev/tb-dev/docker-compose.yml logs -f

# Test health endpoint
curl -I https://tb-dev.emfour.net/api/health

# Check Traefik routing
docker logs traefik | grep tb-dev

# Verify network connectivity
docker network inspect frontend
```

### Common Commands

#### Pipeline Management

```bash
# Trigger development build
git checkout develop
git commit --allow-empty -m "test: trigger dev build"
git push origin develop

# Trigger staging deployment
git checkout staging
git merge develop
git push origin staging

# Create release
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin v1.0.0

# View pipeline status
# Navigate to: https://git.emfour.net/[project]/pipelines
```

#### Container Management

```bash
# Pull latest development image
docker pull $CI_REGISTRY_IMAGE:dev-latest

# Pull latest staging image
docker pull $CI_REGISTRY_IMAGE:staging-latest

# Pull latest production image
docker pull $CI_REGISTRY_IMAGE:prod-latest

# Pull specific version
docker pull $CI_REGISTRY_IMAGE:v1.0.0

# Inspect image manifest (multi-platform)
docker manifest inspect $CI_REGISTRY_IMAGE:latest

# Inspect image labels
docker inspect $CI_REGISTRY_IMAGE:dev-latest --format='{{json .Config.Labels}}' | jq
```

#### Deployment Operations

```bash
# Manual deployment restart
ssh gitlab-deploy@dep-en-dev-01.emfour.net "cd /opt/dev/tb-dev && docker-compose restart"

# View deployment logs
ssh gitlab-deploy@dep-en-dev-01.emfour.net "cd /opt/dev/tb-dev && docker-compose logs -f"

# Manual cleanup (MySQL)
ssh gitlab-deploy@dep-en-dev-01.emfour.net "cd /opt/dev/tb-dev-mysql && docker-compose --profile mysql down -v"

# Manual cleanup (SQLite)
ssh gitlab-deploy@dep-en-dev-01.emfour.net "cd /opt/dev/tb-dev-sqlite && docker-compose down -v"
```

### File Locations

#### Repository Structure

```
trakbridge/
├── .gitlab-ci.yml                     # Main pipeline configuration
├── .gitlab/
│   └── ci/
│       ├── validate.yml               # Validation stage
│       ├── test.yml                   # Test stage
│       ├── security.yml               # Security stage
│       ├── build.yml                  # Build stage
│       ├── deploy.yml                 # Deployment stage
│       └── release.yml                # Release stage
├── docker-compose-dev.yml             # Development compose file
├── docker-compose.staging.yml         # Staging compose file
├── docker-compose.yml                 # Production compose file
├── requirements.txt                   # Python dependencies
├── requirements-dev.txt               # Development dependencies
├── pyproject.toml                     # Project configuration
└── dev/
    └── docs/
        ├── CI_MIGRATION_GUIDE.md
        ├── CI_EXTRACTION_INDEX.md
        ├── EXTRACTED_CI_JOBS.md
        ├── IMPLEMENTATION_CHECKLIST.md
        ├── MIGRATION_COMPLETE.md
        ├── PHASE_2_3_IMPLEMENTATION_SUMMARY.md
        ├── PHASE_4_IMPLEMENTATION_SUMMARY.md
        ├── PHASE_4_QUICK_REFERENCE.md
        ├── PHASE_5_IMPLEMENTATION_SUMMARY.md
        ├── PHASE_5_QUICK_REFERENCE.md
        └── PHASE_6_IMPLEMENTATION_SUMMARY.md
```

### Runner Tags

| Tag | Executor | Purpose | Requirements |
|-----|----------|---------|--------------|
| docker | Docker | Test jobs, validation, security | Docker executor |
| shell | Shell | Build jobs, deployments, releases | Docker daemon access |

### Stage Duration Reference

| Stage | Jobs | Typical Duration | Notes |
|-------|------|------------------|-------|
| validate | 3 | 1-2 minutes | Fast YAML validation |
| test | 6 | 15-30 minutes | Parallel execution |
| security | 3 | 10-20 minutes | Parallel execution |
| build | 1-3 | 45-120 minutes | Multi-platform builds take longer |
| deploy | 1-7 | 5-15 minutes | Includes health checks |
| release | 0-1 | 5-10 minutes | Manual trigger only |

### Support Resources

**GitLab Documentation:**
- CI/CD: https://docs.gitlab.com/ee/ci/
- Includes: https://docs.gitlab.com/ee/ci/includes/
- YAML Anchors: https://docs.gitlab.com/ee/ci/yaml/#anchors
- Reports: https://docs.gitlab.com/ee/ci/yaml/#reports

**Docker Documentation:**
- Buildx: https://docs.docker.com/buildx/
- Multi-platform: https://docs.docker.com/build/building/multi-platform/
- Compose: https://docs.docker.com/compose/

**Python Tools:**
- Black: https://black.readthedocs.io/
- Flake8: https://flake8.pycqa.org/
- pytest: https://docs.pytest.org/
- Bandit: https://bandit.readthedocs.io/
- Safety: https://pyup.io/safety/

---

## Appendix: Complete Pipeline Flow

### Development Workflow

```
Feature Branch
    ↓
Merge to develop
    ↓
validate (3 jobs: YAML, requirements, pyproject)
    ↓
test (6 jobs: quality, unit, integration × 3, compatibility)
    ↓
security (3 jobs: SAST, dependencies, licences)
    ↓
build-dev (45 min: dev-{sha}, dev-latest)
    ↓
deploy-dev-postgres (automatic: tb-dev.emfour.net)
    ↓
[Optional Manual] deploy-dev-mysql (tb-dev-mysql.emfour.net)
    ↓
[Optional Manual] deploy-dev-sqlite (tb-dev-sqlite.emfour.net)
    ↓
Development Testing Complete
```

### Staging Workflow

```
Merge develop to staging
    ↓
validate → test → security
    ↓
build-staging (45 min: staging-{sha}, staging-latest)
    ↓
deploy-staging (automatic: tb-staging.emfour.net)
    ↓
UAT Testing
    ↓
Staging Approval
```

### Production Workflow

```
Merge staging to main OR create git tag
    ↓
validate → test → security
    ↓
build-prod (45-120 min: prod-{sha}/prod-latest OR {tag}/latest)
    ↓
[Manual Trigger] deploy-prod (tb.emfour.net)
    ↓
Production Health Check
    ↓
[Manual Trigger] release-dockerhub
    ↓
Public Distribution (docker.io/emfoursolutions/trakbridge)
```

---

**Document Version:** 1.0
**Last Updated:** 2025-12-14
**Status:** Complete - All 6 phases implemented
**Maintained By:** TrakBridge Development Team
