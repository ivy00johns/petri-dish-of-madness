# docker/backend.Dockerfile
# Builds the PetriDishOfMadness backend (Python 3.11-slim + uvicorn).

FROM python:3.11-slim

# Keep Python output unbuffered so Docker logs are immediate.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install system dependencies (none beyond slim base needed for this stack).
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Copy only the dependency manifest first for better layer caching.
COPY backend/pyproject.toml ./backend/pyproject.toml
COPY backend/petridish/__init__.py ./backend/petridish/__init__.py

# Install the package and all runtime dependencies.
RUN pip install --no-cache-dir ./backend

# Copy the full backend source.
COPY backend/ ./backend/

# Config is mounted at runtime (see docker-compose.yml).
# EM_CONFIG_DIR can be overridden; default points to /app/config.
ENV EM_CONFIG_DIR=/app/config

EXPOSE 8000

# Run from the backend/ directory so the `petridish` package is importable.
WORKDIR /app/backend
CMD ["uvicorn", "petridish.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
