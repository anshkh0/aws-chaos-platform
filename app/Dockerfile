# =============================================================
# STAGE 1 — BUILD + TEST
# Install everything including test dependencies, run pytest.
# This stage never makes it into the final image — it's just
# for validating the code before we package it.
# =============================================================
FROM python:3.12-slim AS builder

WORKDIR /app

# Install dependencies first so Docker can cache this layer.
# If requirements.txt doesn't change, this step is skipped on rebuild.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt pytest

# Copy app code and tests
COPY app.py .
COPY tests/ tests/

# Run tests here — if any test fails, the build stops entirely.
# This means a broken app can never make it to ECR or ECS.
RUN pytest tests/ -v


# =============================================================
# STAGE 2 — PRODUCTION
# Start clean. Copy only what the app needs to run.
# No test libraries, no build tools, smaller and more secure.
# =============================================================
FROM python:3.12-slim AS production

# Run as non-root — security best practice.
# If someone breaks into the container they get a low-privilege user.
RUN useradd -r -s /bin/false appuser

WORKDIR /app

# Install only runtime dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only the app — not the tests
COPY app.py .

# Switch to non-root user before starting
USER appuser

# Gunicorn is a production-grade server, replacing Flask's dev server.
# 2 workers handle concurrent requests without blocking.
EXPOSE 5000
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "30", "app:app"]