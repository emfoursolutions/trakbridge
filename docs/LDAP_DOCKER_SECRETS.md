# LDAP Docker Secrets Configuration Guide

This guide explains how to securely configure LDAP authentication in TrakBridge using Docker secrets for production deployments.

## Overview

TrakBridge supports Docker secrets for secure management of sensitive authentication credentials like LDAP bind passwords. This approach follows security best practices by:

- Storing secrets outside the container filesystem
- Preventing secrets from appearing in environment variables
- Supporting automatic secret rotation
- Maintaining compatibility with Docker Swarm and Kubernetes

## Docker Secrets Support

TrakBridge includes a comprehensive secrets management system with priority-based fallback:

1. **Docker Secrets** (Priority 10 - Highest): Reads from `/run/secrets/`
2. **Environment Variables** (Priority 20): Standard env vars  
3. **_FILE Environment Variable** (Priority 30): File path references
4. **DotEnv Files** (Priority 40 - Development only): Local `.env` files

## LDAP Password Configuration Methods

### Method 1: Direct Docker Secrets (Recommended)

The LDAP bind password can be stored as a Docker secret and automatically resolved by TrakBridge.

#### Step 1: Create the Docker Secret

```bash
# Create secret from file
echo "your-ldap-service-account-password" | docker secret create ldap_bind_password -

# Or create from stdin
docker secret create ldap_bind_password -
# (type password and press Ctrl+D)

# Verify secret creation
docker secret ls
```

#### Step 2: Configure Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  trakbridge:
    image: trakbridge:latest
    secrets:
      - ldap_bind_password
    environment:
      # LDAP configuration
      LDAP_ENABLED: "true"
      LDAP_SERVER: "ldap://your-domain-controller.company.com"
      LDAP_PORT: "389"
      LDAP_BIND_DN: "cn=trakbridge,ou=Service Accounts,dc=company,dc=com"
      LDAP_USER_SEARCH_BASE: "ou=Users,dc=company,dc=com"
      LDAP_GROUP_SEARCH_BASE: "ou=Groups,dc=company,dc=com"
      
      # Role mappings
      LDAP_ADMIN_GROUP: "cn=TrakBridge-Admins,ou=Groups,dc=company,dc=com"
      LDAP_USER_GROUP: "cn=TrakBridge-Users,ou=Groups,dc=company,dc=com"
      LDAP_DEFAULT_ROLE: "user"

secrets:
  ldap_bind_password:
    external: true
```

#### Step 3: Authentication Configuration

TrakBridge will automatically resolve the LDAP bind password from the Docker secret:

```yaml
# config/settings/authentication.yaml
ldap:
  enabled: ${LDAP_ENABLED:-false}
  server: "${LDAP_SERVER:-ldap://your-ad-server.company.com}"
  bind_dn: "${LDAP_BIND_DN:-cn=service,dc=company,dc=com}"
  bind_password: "${LDAP_BIND_PASSWORD:-default}"  # Resolved from secret
```

### Method 2: _FILE Environment Variable

Use the `_FILE` environment variable convention to reference a secret file path.

#### Step 1: Create Docker Secret
```bash
docker secret create ldap_password -
```

#### Step 2: Configure with _FILE Variable
```yaml
# docker-compose.yml
services:
  trakbridge:
    image: trakbridge:latest
    secrets:
      - source: ldap_password
        target: /run/secrets/ldap_password
    environment:
      LDAP_BIND_PASSWORD_FILE: "/run/secrets/ldap_password"
      # ... other LDAP config
```

#### Step 3: TrakBridge Resolution
TrakBridge automatically detects `LDAP_BIND_PASSWORD_FILE` and reads the file content.

### Method 3: External Secrets (Kubernetes/Advanced)

For Kubernetes or external secret managers:

```yaml
# kubernetes-secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: trakbridge-ldap
type: Opaque
data:
  ldap-password: <base64-encoded-password>
```

```yaml
# deployment.yaml
spec:
  containers:
  - name: trakbridge
    env:
    - name: LDAP_BIND_PASSWORD
      valueFrom:
        secretKeyRef:
          name: trakbridge-ldap
          key: ldap-password
```

## Complete Production Example

### Step 1: Create All Required Secrets

```bash
# LDAP service account password
echo "SecureServiceAccountPassword" | docker secret create ldap_bind_password -

# Application secrets
openssl rand -base64 32 | docker secret create secret_key -
openssl rand -base64 32 | docker secret create tb_master_key -
echo "ProductionDBPassword" | docker secret create db_password -
```

### Step 2: Production Docker Compose

```yaml
# docker-compose.prod.yml
version: '3.8'

services:
  trakbridge:
    image: trakbridge:latest
    secrets:
      - ldap_bind_password
      - secret_key
      - tb_master_key
      - db_password
    environment:
      # Application environment
      FLASK_ENV: "production"
      
      # Database configuration
      DB_TYPE: "postgresql"
      DB_HOST: "postgres"
      DB_NAME: "trakbridge"
      DB_USER: "trakbridge"
      
      # LDAP configuration
      LDAP_ENABLED: "true"
      LDAP_SERVER: "ldap://dc01.company.com"
      LDAP_PORT: "389"
      LDAP_USE_TLS: "true"
      LDAP_BIND_DN: "cn=trakbridge,ou=Service Accounts,dc=company,dc=com"
      LDAP_USER_SEARCH_BASE: "ou=Users,dc=company,dc=com"
      LDAP_USER_SEARCH_FILTER: "(sAMAccountName={username})"
      LDAP_GROUP_SEARCH_BASE: "ou=Security Groups,dc=company,dc=com"
      LDAP_GROUP_SEARCH_FILTER: "(member={user_dn})"
      
      # Role mappings
      LDAP_ADMIN_GROUP: "cn=TrakBridge Admins,ou=Security Groups,dc=company,dc=com"
      LDAP_OPERATOR_GROUP: "cn=TrakBridge Operators,ou=Security Groups,dc=company,dc=com"
      LDAP_USER_GROUP: "cn=TrakBridge Users,ou=Security Groups,dc=company,dc=com"
      LDAP_DEFAULT_ROLE: "user"
      
      # Authentication priority (LDAP first, local fallback)
      AUTH_PROVIDER_PRIORITY: "ldap,local"
    networks:
      - trakbridge
    depends_on:
      - postgres

  postgres:
    image: postgres:15
    secrets:
      - db_password
    environment:
      POSTGRES_DB: trakbridge
      POSTGRES_USER: trakbridge
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks:
      - trakbridge

secrets:
  ldap_bind_password:
    external: true
  secret_key:
    external: true
  tb_master_key:
    external: true
  db_password:
    external: true

volumes:
  postgres_data:

networks:
  trakbridge:
    driver: overlay
```

### Step 3: Deploy

```bash
# Initialize Docker Swarm (if not already done)
docker swarm init

# Deploy the stack
docker stack deploy -c docker-compose.prod.yml trakbridge

# Check deployment
docker service ls
docker service logs trakbridge_trakbridge
```

## Security Best Practices

### Secret Management
- **Rotate secrets regularly**: Use `docker secret create` with new names and update services
- **Limit secret access**: Only mount secrets to containers that need them
- **Use external secret stores**: Consider HashiCorp Vault or cloud provider secret services
- **Audit secret usage**: Monitor secret access in production

### LDAP Security
- **Use service accounts**: Create dedicated LDAP service accounts with minimal permissions
- **Enable TLS**: Always use `LDAP_USE_TLS: "true"` in production
- **Restrict search scope**: Use specific OUs in search bases to limit access
- **Validate certificates**: Set `LDAP_VALIDATE_CERT: "true"` for certificate validation

### Network Security
```yaml
# Restrict network access
networks:
  trakbridge:
    driver: overlay
    attachable: false
    ipam:
      config:
        - subnet: 172.20.0.0/16
```

## Troubleshooting

### Secret Not Found
```bash
# Check secret exists
docker secret ls

# Inspect secret (metadata only, not content)
docker secret inspect ldap_bind_password

# Check container mounts
docker exec <container> ls -la /run/secrets/
```

### LDAP Connection Issues
```bash
# Test LDAP connectivity from container
docker exec -it <container> ldapsearch -H ldap://your-server:389 -D "cn=service,dc=company,dc=com" -W -b "dc=company,dc=com" "(sAMAccountName=testuser)"
```

### Configuration Validation
```bash
# Check TrakBridge logs for authentication errors
docker service logs trakbridge_trakbridge | grep -i ldap

# Validate authentication config
docker exec -it <container> python -c "
from config.authentication_loader import load_authentication_config
config = load_authentication_config('production')
print('LDAP Enabled:', config['authentication']['providers']['ldap']['enabled'])
"
```

## Secret Rotation

### Rotating LDAP Password

```bash
# Create new secret with incremented version
echo "NewServiceAccountPassword" | docker secret create ldap_bind_password_v2 -

# Update service to use new secret
docker service update --secret-rm ldap_bind_password --secret-add ldap_bind_password_v2 trakbridge_trakbridge

# Remove old secret after verification
docker secret rm ldap_bind_password
```

### Automated Rotation Script

```bash
#!/bin/bash
# rotate-ldap-secret.sh

SECRET_NAME="ldap_bind_password"
SERVICE_NAME="trakbridge_trakbridge"
NEW_VERSION="_v$(date +%Y%m%d)"

# Read new password
read -s -p "Enter new LDAP password: " NEW_PASSWORD
echo

# Create new secret
echo "$NEW_PASSWORD" | docker secret create "${SECRET_NAME}${NEW_VERSION}" -

# Update service
docker service update \
  --secret-rm "$SECRET_NAME" \
  --secret-add "source=${SECRET_NAME}${NEW_VERSION},target=${SECRET_NAME}" \
  "$SERVICE_NAME"

echo "Secret rotated successfully. Verify service health before removing old secret."
```

## Integration with CI/CD

### GitLab CI Example

```yaml
# .gitlab-ci.yml
deploy_production:
  stage: deploy
  script:
    - echo "$LDAP_BIND_PASSWORD" | docker secret create ldap_bind_password_${CI_COMMIT_SHA} -
    - docker stack deploy -c docker-compose.prod.yml trakbridge
  environment:
    name: production
  only:
    - main
```

### GitHub Actions Example

```yaml
# .github/workflows/deploy.yml
- name: Create Docker secrets
  run: |
    echo "${{ secrets.LDAP_BIND_PASSWORD }}" | docker secret create ldap_bind_password -
    echo "${{ secrets.DB_PASSWORD }}" | docker secret create db_password -
```

This approach ensures your LDAP credentials remain secure while maintaining operational flexibility for production deployments.