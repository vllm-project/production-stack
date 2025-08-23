FROM python:3.12-slim

# Copy uv from the official uv Docker image (pinned version for reproducibility)
COPY --from=ghcr.io/astral-sh/uv:0.8.3 /uv /uvx /bin/

# Set environment variables for uv
ENV UV_SYSTEM_PYTHON=1

WORKDIR /app

# hadolint ignore=DL3008
RUN --mount=type=cache,target=/var/lib/apt --mount=type=cache,target=/var/cache/apt \
    apt-get update && \
    apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

# Copy the git metadata and source code
COPY .git/ .git/
COPY src/ src/

ARG INSTALL_OPTIONAL_DEP=semantic_cache,lmcache
ENV INSTALL_OPTIONAL_DEP=${INSTALL_OPTIONAL_DEP}

# Install dependencies first (for better Docker layer caching)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    if [ -n "$INSTALL_OPTIONAL_DEP" ]; then \
        OLD_IFS="$IFS"; IFS=','; \
        set --; \
        for dep in $INSTALL_OPTIONAL_DEP; do \
            [ -n "$dep" ] && set -- "$@" --extra "$dep"; \
        done; \
        IFS="$OLD_IFS"; \
        uv sync --locked "$@"; \
    else \
        uv sync --locked; \
    fi

# Set the entrypoint
ENTRYPOINT ["vllm-router"]
CMD []
