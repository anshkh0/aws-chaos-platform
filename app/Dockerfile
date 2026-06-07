FROM python:3.12-slim AS builder

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt pytest

# Copy app code and tests
COPY app.py .
COPY tests/ tests/

# Run tests here and if any test fails, the build stops entirely.
RUN pytest tests/ -v


 #PRODUCTION
FROM python:3.12-slim AS production

RUN useradd -r -s /bin/false appuser

WORKDIR /app

# Installing only runtime dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Switch to non-root user before starting
USER appuser

EXPOSE 5000
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "30", "app:app"]