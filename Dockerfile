# =============================================================================
# Dockerfile — Trading Bot
# =============================================================================

FROM python:3.12-slim

LABEL maintainer="trading-bot"
LABEL description="EV-based algorithmic trading bot"

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (leverage Docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create required directories
RUN mkdir -p logs data/reports

# Non-root user for security
RUN useradd -m -u 1000 botuser && chown -R botuser:botuser /app
USER botuser

# Expose API port
EXPOSE 8000

# Default command: paper trading mode
CMD ["python", "-m", "app.main"]
