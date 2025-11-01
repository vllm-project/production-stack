#  This template is provided as an example for CPU deployment but isn't included in the terraform deployment.
servingEngineSpec:
  enableEngine: true
  runtimeClassName: "" # Use default runtime for CPU
  startupProbe:
    initialDelaySeconds: 60
    periodSeconds: 30
    failureThreshold: 120
    httpGet:
      path: /health
      port: 8000
  nodeSelector:
    workload-type: cpu
    node-group: cpu-pool
  containerSecurityContext:
    privileged: true
  modelSpec:
  - name: "tinyllama-cpu"
    repository: "public.ecr.aws/q9t5s3a7/vllm-cpu-release-repo"
    tag: "v0.8.5.post1"
    modelURL: "/data/models/tinyllama"
    replicaCount: 1
    requestCPU: 1
    requestMemory: "2Gi"
    requestGPU: 0
    limitCPU: 2
    limitMemory: "6Gi"
    pvcStorage: "10Gi"
    storageClass: "compute-csi-default-sc"  # nebius default storage class
    vllmConfig:
      dtype: "bfloat16"
      extraArgs:
        - "--device=cpu"
        - "--no-enable-prefix-caching"
    env:
      - name: VLLM_CPU_KVCACHE_SPACE
        value: "1"
      - name: VLLM_CPU_OMP_THREADS_BIND
        value: "0-1"
    initContainer:
      name: downloader
      image: python:3.11-slim
      command: ["/bin/sh","-c"]
      args:
        - |
          pip install --no-cache-dir --timeout=300 "huggingface_hub[cli]" &&
          huggingface-cli download TinyLlama/TinyLlama-1.1B-Chat-v1.0 \
            --local-dir /data/models/tinyllama \
            --local-dir-use-symlinks False
      env:
        - name: HUGGING_FACE_HUB_TOKEN
          valueFrom:
            secretKeyRef:
              name: hf-token-secret
              key: token
      resources:
        requests:
          cpu: "500m"
          memory: "1Gi"
        limits:
          memory: "2Gi"
      mountPvcStorage: true

routerSpec:
  enableRouter: true
  routingLogic: "roundrobin"
  resources:
    requests:
      cpu: "500m"
      memory: "1Gi"
    limits:
      cpu: "1"
      memory: "2Gi"

  # NGINX Ingress configuration for the router
  ingress:
    enabled: true
    className: "nginx"  # Changed from ALB to NGINX
    annotations:
      # Basic NGINX Ingress Controller annotations
      nginx.ingress.kubernetes.io/ssl-redirect: "true"
      nginx.ingress.kubernetes.io/backend-protocol: "HTTP"

      # Health check configuration (NGINX way)
      nginx.ingress.kubernetes.io/upstream-fail-timeout: "30s"
      nginx.ingress.kubernetes.io/upstream-max-fails: "3"

      # Request size limits for large model requests/responses
      nginx.ingress.kubernetes.io/proxy-body-size: "100m"
      nginx.ingress.kubernetes.io/client-max-body-size: "100m"

      # Timeout configurations for AI model inference
      nginx.ingress.kubernetes.io/proxy-connect-timeout: "60"
      nginx.ingress.kubernetes.io/proxy-send-timeout: "300"
      nginx.ingress.kubernetes.io/proxy-read-timeout: "300"

      # TLS/SSL configuration with cert-manager
      cert-manager.io/cluster-issuer: letsencrypt-prod

    hosts:
      - host: vllm-api.${nginx_ip_hex}.sslip.io  # Or Using your nip.io pattern
        paths:
          - path: /
            pathType: Prefix

    # TLS configuration with automatic certificate
    tls:
      - secretName: vllm-tls-secret
        hosts:
          - vllm-api.${nginx_ip_hex}.sslip.io # Or Using your nip.io pattern
