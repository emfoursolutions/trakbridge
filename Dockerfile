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

# Create a flexible user creation script
RUN echo '#!/bin/bash\n\
set -e\n\
USER_ID=${USER_ID:-1000}\n\
GROUP_ID=${GROUP_ID:-1000}\n\
\n\
# Create group if it doesn'\''t exist\n\
if ! getent group $GROUP_ID > /dev/null 2>&1; then\n\
    groupadd -g $GROUP_ID appuser\n\
fi\n\
\n\
# Create user if it doesn'\''t exist\n\
if ! getent passwd $USER_ID > /dev/null 2>&1; then\n\
    useradd -r -u $USER_ID -g $GROUP_ID -d /app -s /bin/bash appuser\n\
fi\n\
\n\
# Fix ownership of app directories\n\
chown -R $USER_ID:$GROUP_ID /app/logs /app/data /app/tmp\n\
\n\
# Fix ownership and permissions of secrets if they exist\n\
if [ -d "/app/secrets" ]; then\n\
    chown -R $USER_ID:$GROUP_ID /app/secrets\n\
    chmod -R 640 /app/secrets/*\n\
fi\n\
\n\
# Execute the main entrypoint as the specified user\n\
exec gosu $USER_ID:$GROUP_ID "$@"\n\
' > /usr/local/bin/docker-entrypoint.sh && \
    chmod +x /usr/local/bin/docker-entrypoint.sh

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