# Use a slim Python 3.11 image
FROM python:3.11-slim

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies into a system-wide environment (no venv needed in container)
RUN uv pip install --system --requirement pyproject.toml

# Copy the rest of the application code
COPY . .

# Expose the web server port
EXPOSE 8000

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Default command: launch the web demo
# We bind to 0.0.0.0 to allow traffic from outside the container
CMD ["python", "main.py", "serve", "--host", "0.0.0.0"]
