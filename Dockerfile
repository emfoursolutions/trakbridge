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

# Clean any cached build artifacts and install the package
RUN rm -rf build/ dist/ *.egg-info/ __pycache__ */__pycache__ \
    && find . -name "*.pyc" -delete \
    && pip cache purge \
    && pip install --no-cache-dir --force-reinstall .

# Production stage
FROM python:3.12-slim AS production

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app" \
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

# Copy essential config files first
COPY hypercorn.toml /app/
COPY docker/entrypoint.sh /app/

# Copy all application source code and ensure it overwrites any installed package
COPY . /app/

# Debug: List what files were copied
RUN echo "=== DEBUG: Files in /app after COPY ===" && \
    find /app -type f -name "*.py" | head -20 && \
    echo "=== DEBUG: Utils directory contents ===" && \
    ls -la /app/utils/ || echo "utils directory not found" && \
    echo "=== DEBUG: Checking specific files ===" && \
    ls -la /app/utils/json_validator.py || echo "json_validator.py not found" && \
    ls -la /app/utils/security_helpers.py || echo "security_helpers.py not found"

# Copy the generated _version.py from builder
COPY --from=builder /app/_version.py /app/

# Debug: Check files before install
RUN echo "=== DEBUG: Files before pip install ===" && \
    python -c "import os; print('Current dir:', os.getcwd())" && \
    python -c "import os; print('Utils exists:', os.path.exists('/app/utils'))" && \
    python -c "import os; print('json_validator exists:', os.path.exists('/app/utils/json_validator.py'))"

# Install the application to ensure proper Python package resolution
RUN pip install --no-cache-dir --force-reinstall .

# Debug: Check Python path and package after install
RUN echo "=== DEBUG: Python setup after install ===" && \
    python -c "import sys; print('Python path:'); [print(p) for p in sys.path]" && \
    python -c "import pkg_resources; print('Installed packages:'); [print(d) for d in pkg_resources.working_set if 'trakbridge' in str(d)]" && \
    python -c "import os; print('Site-packages trakbridge:'); [print(f) for f in os.listdir('/opt/venv/lib/python3.12/site-packages/') if 'trakbridge' in f]" || echo "No trakbridge in site-packages"

# Ensure proper permissions for runtime directories (after copy to avoid overwriting)
RUN mkdir -p /app/logs /app/data /app/tmp && \
    chmod 755 /app && \
    chmod 777 /app/logs /app/data /app/tmp

# Make entrypoint executable
RUN chmod +x /app/entrypoint.sh

# Create default non-root user for security
RUN groupadd -g 1000 appuser && \
    useradd -r -u 1000 -g appuser -d /app -s /bin/bash appuser

# Set ownership for directories that appuser needs access to
RUN chown -R appuser:appuser /app/logs /app/data /app/tmp /app/entrypoint.sh
# Ensure appuser can read application code directories for Python imports
RUN chown -R appuser:appuser /app/utils /app/plugins /app/services /app/models /app/routes /app/config

# Note: Container starts as root to allow dynamic user creation
# The /app/entrypoint.sh script will handle user switching based on USER_ID/GROUP_ID
# and default to appuser (1000:1000) if no dynamic user is requested

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT:-5000}/api/health || exit 1

EXPOSE 5000
ENTRYPOINT ["/app/entrypoint.sh"]
CMD []

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