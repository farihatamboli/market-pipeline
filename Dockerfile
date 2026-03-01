FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Create data and log dirs
RUN mkdir -p data logs

EXPOSE 5050

# Default: run dashboard
# Override with: docker compose run pipeline
CMD ["python", "-m", "dashboard.app"]
