FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install poetry first
RUN pip install --no-warn-script-location poetry && \
    poetry config virtualenvs.create false

# Copy project files needed for poetry
COPY pyproject.toml README.md ./

# Install dependencies only (not the project itself)
RUN poetry install --only=main --no-root

# Copy application code
COPY . .

# Create non-root user
RUN useradd --create-home app && chown -R app:app /app
USER app

# Expose port for Cloud Run
EXPOSE 8080

# Start application
CMD uvicorn src.safr_backend.main:app --host 0.0.0.0 --port $PORT