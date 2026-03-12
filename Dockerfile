# Energy AI Agent - Dockerfile
# Containerizes the energy market prediction system

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=America/New_York

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    make \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for better caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Download NLTK data (required for textblob)
RUN python -c "import nltk; nltk.download('punkt', quiet=True); nltk.download('brown', quiet=True)"

# Copy application code
COPY . .

# Create data directory if it doesn't exist
RUN mkdir -p data scripts models logs

# Make entrypoint script executable
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

# Set default command
ENTRYPOINT ["/app/docker-entrypoint.sh"]
