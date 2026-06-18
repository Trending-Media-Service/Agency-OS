# ==========================================================
# Stage 1: Builder
# ==========================================================
FROM python:3.12-slim AS builder

# Install system tools needed for downloading/unzipping Terraform and building wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Download and unzip Terraform CLI (1.5.7)
ENV TERRAFORM_VERSION=1.5.7
RUN curl -LO "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" \
    && unzip "terraform_${TERRAFORM_VERSION}_linux_amd64.zip" \
    && chmod +x terraform

# Create a virtual environment and install python dependencies
WORKDIR /app
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt


# ==========================================================
# Stage 2: Runner
# ==========================================================
FROM python:3.12-slim AS runner

# Install only runtime system dependencies
# ca-certificates: for secure HTTPS calls
# git: required by ProvisionAdapter for cloning/pushing recipe repos
# curl: required for Docker HEALTHCHECK and debugging
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy Terraform CLI from the builder stage
COPY --from=builder /app/terraform /usr/local/bin/terraform

# Copy python virtual environment from the builder stage
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create a secure, dedicated non-root system user and group
# Using UID/GID 10001 to avoid conflicts with host users
RUN groupadd -g 10001 appgroup && \
    useradd -r -u 10001 -g appgroup -d /app -s /sbin/nologin appuser

# Establish working directory and ensure correct ownership
WORKDIR /app
RUN mkdir -p /app /recipes && \
    chown -R appuser:appgroup /app /recipes

# Copy application code and recipes with correct ownership
COPY --chown=appuser:appgroup app/ /app/app/
COPY --chown=appuser:appgroup migrate.py /app/
COPY --chown=appuser:appgroup recipes/ /recipes/

# Expose FastAPI port
EXPOSE 8080

# Switch to the non-root user
USER 10001

# Native Docker container health check using our /healthz endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8080/healthz || exit 1

# Run FastAPI app under uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
