FROM python:3.12-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . .

# Non-root user for security
RUN useradd -m -u 1001 bandhan && chown -R bandhan:bandhan /app
USER bandhan

EXPOSE ${PORT:-8000}

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# Use $PORT for Railway/Render compatibility; default to 8000 for local
CMD sh -c "gunicorn app.main:app \
     --worker-class uvicorn.workers.UvicornWorker \
     --workers 2 \
     --bind 0.0.0.0:${PORT:-8000} \
     --access-logfile - \
     --error-logfile - \
     --log-level info"
