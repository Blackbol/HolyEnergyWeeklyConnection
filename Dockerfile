FROM python:3.12-slim

WORKDIR /app

# Install dependencies in a separate layer so they're cached on rebuilds.
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy source and install the package itself (no re-download of deps).
COPY src/ src/
RUN pip install --no-cache-dir --no-deps -e .

# Drop root privileges — the script only needs network access.
RUN useradd --create-home appuser
USER appuser

# Default command for standalone use: docker run --rm holy-energy
# Overridden to "sleep infinity" by docker-compose so Ofelia can exec weekly.
CMD ["python", "-m", "holy_energy_weekly_connection"]
