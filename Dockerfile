# =============================================================================
# Multi-stage Dockerfile for TrakBridge (pyproject.toml-based)
# =============================================================================

# ===============================
# Stage 1 — Builder Stage
# ===============================
FROM python:3.12-slim AS builder

ARG BUILD_ENV=production

# Install system dependencies for building
RUN apt-get update && apt-get install -y \
    build-essential \
    pkg-config \
    default-libmysqlclient-dev \
    libpq-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install build tools and setuptools-scm
COPY pyproject.toml .
COPY requirements.txt .  # Optional, may contain dev-only deps
RUN pip install --no-cache-dir --upgrade pip setuptools build setuptools-scm

# Copy app source for install
COPY . .

# Install package (build from pyproject.toml)
RUN pip install .

# ===============================
# Stage 2 — Final Production Image
# ===============================
FROM python:3.12-slim AS production

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    FLASK_ENV=production \
    USER_ID=1000 \
    GROUP_ID=1000

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
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

# Create app directories
WORKDIR /app
RUN mkdir -p /app/logs /app/data /app/tmp && \
    chown -R appuser:appuser /app

# Copy runtime files
COPY --chown=appuser:appuser . /app/
COPY --chown=appuser:appuser hypercorn.toml /app/hypercorn.toml
COPY --chown=appuser:appuser docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

USER appuser

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT:-5000}/api/health || exit 1

EXPOSE 5000
ENTRYPOINT ["/app/entrypoint.sh"]
CMD []

# ===============================
# Stage 3 — Development Image
# ===============================
FROM production AS development

ENV FLASK_ENV=development

USER root

RUN apt-get update && apt-get install -y \
    git \
    vim \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    flask-debugtoolbar \
    pytest \
    pytest-cov \
    black \
    flake8

USER appuser
