FROM python:3.12-slim

WORKDIR /app

# hadolint ignore=DL3008
RUN --mount=type=cache,target=/var/lib/apt --mount=type=cache,target=/var/cache/apt \
    apt-get update && \
    apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

# Copy the setup.dot py and the git metadata first (leverage Docker layer caching)
COPY setup.py .
COPY .git/ .git/

# Copy the rest of the application code
COPY src/ src/

ARG INSTALL_SENTENCE_TRANSFORMERS=true
ENV INSTALL_SENTENCE_TRANSFORMERS=${INSTALL_SENTENCE_TRANSFORMERS}

# Install dependencies (use cache, and delete after install, to speed up the build)
RUN pip install --upgrade --no-cache-dir pip setuptools_scm && \
    pip install --no-cache-dir .

# Set the entrypoint
ENTRYPOINT ["vllm-router"]
CMD []
