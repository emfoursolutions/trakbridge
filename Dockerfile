# =============================================================================
# Optimized Multi-stage Dockerfile for TrakBridge
# =============================================================================

# ===============================
# Stage 1 — Builder Stage (OPTIMIZED)
# ===============================
FROM python:3.12-slim AS builder

ARG BUILD_ENV=production
ARG SETUPTOOLS_SCM_PRETEND_VERSION
ENV SETUPTOOLS_SCM_PRETEND_VERSION=$SETUPTOOLS_SCM_PRETEND_VERSION

# Install system dependencies for building - OPTIMIZED
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    pkg-config \
    default-libmysqlclient-dev \
    libpq-dev \
    git \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create virtual environment with specific Python path
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade pip and install build tools in one layer
RUN pip install --no-cache-dir --upgrade \
    pip \
    setuptools \
    wheel \
    build \
    setuptools-scm

# Copy only what's needed for dependency installation first
COPY pyproject.toml README.md ./
COPY _version.py ./ 2>/dev/null || true

# Install dependencies first (better caching)
RUN pip install --no-cache-dir -e .

# Copy rest of the application
COPY . .

# Build the package
RUN pip install --no-cache-dir .

# ===============================
# Stage 2 — Final Production Image (OPTIMIZED)
# ===============================
FROM python:3.12-slim AS production

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    FLASK_ENV=production \
    USER_ID=1000 \
    GROUP_ID=1000

# Install only runtime dependencies - OPTIMIZED
RUN apt-get update && apt-get install -y --no-install-recommends \
    default-mysql-client \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user
RUN groupadd -g ${GROUP_ID} appuser && \
    useradd -r -u ${USER_ID} -g appuser -d /app -s /bin/bash appuser

# Copy virtualenv from builder
COPY --from=builder /opt/venv /opt/venv

# Create app directories and set permissions
WORKDIR /app
RUN mkdir -p /app/logs /app/data /app/tmp && \
    chown -R appuser:appuser /app

# Copy runtime files with proper ownership
COPY --chown=appuser:appuser hypercorn.toml /app/
COPY --chown=appuser:appuser docker/entrypoint.sh /app/
RUN chmod +x /app/entrypoint.sh

# Copy application code
COPY --chown=appuser:appuser . /app/

USER appuser

# Optimized health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT:-5000}/api/health || exit 1

EXPOSE 5000
ENTRYPOINT ["/app/entrypoint.sh"]
CMD []

# ===============================
# Stage 3 — Development Image (OPTIMIZED)
# ===============================
FROM production AS development

ENV FLASK_ENV=development

USER root

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

USER appuser