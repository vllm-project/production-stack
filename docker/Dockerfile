FROM python:3.12-slim

WORKDIR /app

# hadolint ignore=DL3008
RUN --mount=type=cache,target=/var/lib/apt --mount=type=cache,target=/var/cache/apt \
    apt-get update && \
    apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

# Copy the pyproject.toml and the git metadata first (leverage Docker layer caching)
COPY pyproject.toml .
COPY .git/ .git/

# Copy only production code (exclude tests and examples)
COPY src/vllm_router/ src/vllm_router/
COPY src/gateway_inference_extension/ src/gateway_inference_extension/

ARG INSTALL_OPTIONAL_DEP=semantic_cache,lmcache
ENV INSTALL_OPTIONAL_DEP=${INSTALL_OPTIONAL_DEP}

# Install dependencies (use cache, and delete after install, to speed up the build)
RUN pip install --upgrade --no-cache-dir pip setuptools_scm && \
    pip install --no-cache-dir .[$INSTALL_OPTIONAL_DEP]

# Set the entrypoint
ENTRYPOINT ["vllm-router"]
CMD []
