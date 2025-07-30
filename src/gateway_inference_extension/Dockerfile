# Dockerfile has specific requirement to put this ARG at the beginning:
# https://docs.docker.com/engine/reference/builder/#understand-how-arg-and-from-interact
ARG BUILDER_IMAGE=golang:1.24
ARG BASE_IMAGE=gcr.io/distroless/static:nonroot

## Multistage build
FROM ${BUILDER_IMAGE} AS builder
ENV CGO_ENABLED=0
ENV GOOS=linux
ENV GOARCH=amd64
ARG COMMIT_SHA=unknown
ARG BUILD_REF

# Install git for applying patch
RUN apt-get update && apt-get install -y git

# Dependencies
WORKDIR /src

COPY * /src
# Clone repo and apply patch
RUN git clone https://github.com/kubernetes-sigs/gateway-api-inference-extension.git && \
    cd gateway-api-inference-extension && \
    git checkout e8834c311ed599e2a99f85328cf2e0ae143402c3 && \
    cd .. && \
    cp /src/scheduler.patch gateway-api-inference-extension/pkg/epp/scheduling/ && \
    cd gateway-api-inference-extension/pkg/epp/scheduling/ && \
    git apply scheduler.patch && \
    cd ../../../.. && \
    cp /src/roundrobin_picker.go  gateway-api-inference-extension/pkg/epp/scheduling/plugins/picker/roundrobin_picker.go && \
    mkdir -p /src/pkg/ && \
    cp -r gateway-api-inference-extension/pkg/epp/ /src/pkg/epp && \
    cp gateway-api-inference-extension/go.mod /src && \
    cp gateway-api-inference-extension/go.sum /src && \
    cp -r gateway-api-inference-extension/cmd/epp /src/cmd && \
    cp -r gateway-api-inference-extension/internal /src/internal && \
    cp -r gateway-api-inference-extension/api /src/api

# Sources
RUN go mod download
WORKDIR /src/cmd
RUN go build -ldflags="-X sigs.k8s.io/gateway-api-inference-extension/pkg/epp/metrics.CommitSHA=${COMMIT_SHA} -X sigs.k8s.io/gateway-api-inference-extension/pkg/epp/metrics.BuildRef=${BUILD_REF}" -o /epp

## Multistage deploy
FROM ${BASE_IMAGE}

WORKDIR /
COPY --from=builder /epp /epp

ENTRYPOINT ["/epp"]
