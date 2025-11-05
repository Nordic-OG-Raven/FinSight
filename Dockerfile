# Dockerfile for Railway deployment
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for Arelle and lxml
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libxml2-dev \
    libxslt-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY api/ ./api/
COPY src/ ./src/
COPY database/ ./database/
COPY config.py .
COPY load_missing_to_railway.py .

# Create data directory
RUN mkdir -p api/data

# Expose port (Railway will override with PORT env var)
EXPOSE 5000

# Run with gunicorn (use shell form for variable expansion)
CMD sh -c "gunicorn api.main:app --bind 0.0.0.0:${PORT:-5000} --timeout 600 --workers 1 --log-level info"

