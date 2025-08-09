#=============================================================================
# Flexible Multi-stage Dockerfile for TrakBridge
# =============================================================================

FROM python:3.12-slim AS builder

ARG SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${SETUPTOOLS_SCM_PRETEND_VERSION}

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    pkg-config \
    default-libmysqlclient-dev \
    libpq-dev \
    libxml2-dev \
    libxslt1-dev \
    zlib1g-dev \
    git \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade pip and install build tools
RUN pip install --no-cache-dir --upgrade pip setuptools wheel setuptools-scm

# Copy all files
COPY . /app
WORKDIR /app

# Configure git for setuptools-scm - ensure we have a valid git repo
RUN git config --global --add safe.directory /app || true

# Install the package
RUN pip install --no-cache-dir .

# Production stage
FROM python:3.12-slim AS production

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    FLASK_ENV=production

# Install runtime dependencies including gosu for user switching
RUN apt-get update && apt-get install -y --no-install-recommends \
    default-mysql-client \
    postgresql-client \
    curl \
    gosu \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy virtualenv from builder
COPY --from=builder /opt/venv /opt/venv

# Create app directories with broad permissions initially
WORKDIR /app
RUN mkdir -p /app/logs /app/data /app/tmp && \
    chmod 755 /app && \
    chmod 777 /app/logs /app/data /app/tmp

# Copy application files (without --chown to allow flexibility)
COPY hypercorn.toml /app/
COPY docker/entrypoint.sh /app/
COPY . /app/

# Copy the generated _version.py from builder
COPY --from=builder /app/_version.py /app/

# Make entrypoint executable
RUN chmod +x /app/entrypoint.sh

# Create default non-root user for security
RUN groupadd -g 1000 appuser && \
    useradd -r -u 1000 -g appuser -d /app -s /bin/bash appuser

# Set ownership for directories that appuser needs access to
RUN chown -R appuser:appuser /app/logs /app/data /app/tmp /app/entrypoint.sh
# Ensure appuser can read application code directories for Python imports
RUN chown -R appuser:appuser /app/utils /app/plugins /app/services /app/models /app/routes /app/config

# Create enhanced security-focused user switching script
RUN echo '#!/bin/bash\n\
set -e\n\
\n\
# Get target UID/GID from environment or current user\n\
TARGET_UID=${USER_ID:-$(id -u)}\n\
TARGET_GID=${GROUP_ID:-$(id -g)}\n\
CURRENT_UID=$(id -u)\n\
\n\
# Debug: Show environment variables and current state\n\
echo "=== Docker Entrypoint Debug Info ==="\n\
echo "USER_ID environment variable: ${USER_ID:-not set}"\n\
echo "GROUP_ID environment variable: ${GROUP_ID:-not set}"\n\
echo "TARGET_UID (resolved): $TARGET_UID"\n\
echo "TARGET_GID (resolved): $TARGET_GID"\n\
echo "CURRENT_UID: $CURRENT_UID"\n\
echo "Current user: $(whoami)"\n\
echo "====================================="\n\
\n\
# Security check: prevent running as root unless explicitly needed\n\
if [[ $CURRENT_UID -eq 0 ]]; then\n\
    # We are running as root - handle user switching securely\n\
    if [[ $TARGET_UID -eq 0 ]] && [[ "${ALLOW_ROOT:-false}" != "true" ]]; then\n\
        echo "ERROR: Running as root is not allowed for security reasons."\n\
        echo "Set ALLOW_ROOT=true environment variable to override this protection."\n\
        echo "For production deployments, consider using USER_ID and GROUP_ID instead."\n\
        exit 1\n\
    fi\n\
    \n\
    # Create or modify user if dynamic UID/GID is requested\n\
    if [[ $TARGET_UID -ne 1000 ]] || [[ $TARGET_GID -ne 1000 ]]; then\n\
        echo "Creating dynamic user with UID:$TARGET_UID GID:$TARGET_GID for host compatibility"\n\
        \n\
        # Create group if it doesn'\''t exist\n\
        if ! getent group $TARGET_GID > /dev/null 2>&1; then\n\
            groupadd -g $TARGET_GID appuser-dynamic\n\
        fi\n\
        \n\
        # Create user if it doesn'\''t exist\n\
        if ! getent passwd $TARGET_UID > /dev/null 2>&1; then\n\
            useradd -r -u $TARGET_UID -g $TARGET_GID -d /app -s /bin/bash appuser-dynamic\n\
        fi\n\
        \n\
        # Fix ownership of app directories for dynamic user\n\
        chown -R $TARGET_UID:$TARGET_GID /app/logs /app/data /app/tmp\n\
        # Fix ownership of all application code directories for Python imports\n\
        chown -R $TARGET_UID:$TARGET_GID /app/utils /app/plugins /app/services /app/models /app/routes /app/config\n\
        \n\
        # Fix ownership and permissions of secrets if they exist\n\
        if [ -d "/app/secrets" ]; then\n\
            chown -R $TARGET_UID:$TARGET_GID /app/secrets\n\
            chmod -R 640 /app/secrets/* 2>/dev/null || true\n\
        fi\n\
    else\n\
        echo "Using default appuser (1000:1000)"\n\
    fi\n\
    \n\
    # Switch to target user using gosu\n\
    echo "Switching to user $TARGET_UID:$TARGET_GID"\n\
    exec gosu $TARGET_UID:$TARGET_GID "$@"\n\
else\n\
    # Already running as non-root user, proceed normally\n\
    echo "Running as non-root user $(id -u):$(id -g)"\n\
    exec "$@"\n\
fi' > /usr/local/bin/docker-entrypoint.sh && \
    chmod +x /usr/local/bin/docker-entrypoint.sh

# Note: Container starts as root to allow dynamic user creation
# The entrypoint script will switch to appropriate user based on USER_ID/GROUP_ID
# or default to appuser (1000:1000) if no dynamic user is requested

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT:-5000}/api/health || exit 1

EXPOSE 5000
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["/app/entrypoint.sh"]

# Development stage
FROM production AS development

ENV FLASK_ENV=development

# Install development tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    vim \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Install development dependencies
RUN pip install --no-cache-dir \
    flask-debugtoolbar \
    pytest \
    pytest-cov \
    pytest-xdist \
    black \
    flake8