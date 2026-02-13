# This file is a Go template. Variables passed from Terraform are accessed with .VarName
servingEngineSpec:
  enableEngine: true
  runtimeClassName: ""  # Use nvidia default runtime for GPU
  tolerations:
    - key: "nvidia.com/gpu"
      operator: "Exists"
      effect: "NoSchedule"
  startupProbe:
    initialDelaySeconds: 180  # <- was 60, give it 3 min
    periodSeconds: 30
    failureThreshold: 120
    httpGet:
      path: /health
      port: 8000
  nodeSelector:
    workload-type: gpu
    node-group: gpu-pool
  containerSecurityContext:
    privileged: true
  modelSpec:
  - name: "tinyllama-gpu"
    repository: "vllm/vllm-openai"
    tag: "v0.8.5.post1"
    modelURL: "/data/models/tinyllama"
    replicaCount: 1
    requestCPU: 1
    requestMemory: "2Gi"
    requestGPU: 1
    limitCPU: 2
    limitMemory: "12Gi"
    pvcStorage: "20Gi"
    storageClass: "compute-csi-default-sc"  # nebius default storage class
    vllmConfig:
      dtype:  "float16"   # Using float16 for broader compatibility, though L40S supports bfloat16.
      extraArgs:
        - "--disable-log-requests"
        - "--gpu-memory-utilization=0.8"  # GPU-specific optimization
    env: []        # NEW: CPU env vars removed
    #   - name: VLLM_CPU_KVCACHE_SPACE
    #     value: "1"
    #   - name: VLLM_CPU_OMP_THREADS_BIND
    #     value: "0-1"
    initContainer:
      name: downloader
      image: python:3.11-slim
      command: ["/bin/sh","-c"]
      args:
        - |
          pip install --no-cache-dir --timeout=300 "huggingface_hub" &&
          hf download TinyLlama/TinyLlama-1.1B-Chat-v1.0 \
            --local-dir /data/models/tinyllama
      env:
        - name: HUGGING_FACE_HUB_TOKEN
          valueFrom:
            secretKeyRef:
              name: hf-token-secret
              key: token
      resources:
        requests:
          cpu: "1"
          memory: "1Gi"
        limits:
          memory: "3Gi"
          cpu: "2"
      mountPvcStorage: true

routerSpec:
  enableRouter: true
  routingLogic: "roundrobin"
  resources:
    requests:
      cpu: "1"
      memory: "1Gi"
    limits:
      cpu: "2"
      memory: "2Gi"

   # Ingress configuration for the router
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
      - host: vllm-api.${nginx_ip_hex}.nip.io  # Or Using your sslip.io , traefik.me  pattern
        paths:
          - path: /
            pathType: Prefix

    # TLS configuration with automatic certificate
    tls:
      - secretName: vllm-tls-secret
        hosts:
          - vllm-api.${nginx_ip_hex}.nip.io # Or Using your  sslip.io pattern
