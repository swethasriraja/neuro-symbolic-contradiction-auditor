# ── Neuro-Symbolic Auditor — Production Dockerfile ─────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# System dependencies for compilation and healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Layer-cached Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

# Copy source tree
COPY . .

# Environment defaults
ENV PYTHONUNBUFFERED=1 \
    PORT=8000

EXPOSE 8000

# Healthcheck probe
HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Production server start
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
