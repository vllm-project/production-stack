# Stage 1: Build
FROM python:3.10-slim as builder

WORKDIR /app

# Copy only the setup.py first to leverage Docker layer caching
COPY setup.py .

# Copy the rest of the application code
COPY src/ src/

# Install dependencies (no cache to reduce size)
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Set the entrypoint
ENTRYPOINT ["vllm-router"]
CMD []
