# Python 3.12 base slim image
FROM python:3.12-slim

# Install system dependencies + Terraform CLI (1.5.7)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    unzip \
    ca-certificates \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install pinned Terraform CLI
ENV TERRAFORM_VERSION=1.5.7
RUN curl -LO "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" \
    && unzip "terraform_${TERRAFORM_VERSION}_linux_amd64.zip" \
    && mv terraform /usr/local/bin/ \
    && rm "terraform_${TERRAFORM_VERSION}_linux_amd64.zip"

# Establish working directory
WORKDIR /app

# Copy and install pinned python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ /app/app/
COPY migrate.py /app/

# Expose FastAPI port
EXPOSE 8080

# Run FastAPI app by default
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
