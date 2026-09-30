FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy source, readme, and install package in editable mode
COPY README.md ./
COPY src/ src/
RUN pip install --no-cache-dir --no-deps -e .

# Create non-root user and prepare persistent data directory
RUN useradd --create-home appuser && \
    mkdir -p /app/data && \
    chown -R appuser:appuser /app

USER appuser

VOLUME ["/app/data"]

ENTRYPOINT ["holy-connect"]
CMD ["daemon"]
