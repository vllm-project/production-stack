# This file is a Go template. Variables passed from Terraform are accessed with .VarName
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
    storageClass: "gp2"
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
   # Ingress configuration for the router
  ingress:
    enabled: true
    className: "alb"  # Use ALB ingress controller for EKS
    annotations:
      # AWS Load Balancer Controller annotations
      kubernetes.io/ingress.class: alb
      alb.ingress.kubernetes.io/scheme: internet-facing
      alb.ingress.kubernetes.io/target-type: ip
      alb.ingress.kubernetes.io/listen-ports: '[{"HTTP": 80}]'   # Remove HTTPS: 443
      # remove alb.ingress.kubernetes.io/ssl-redirect: '443'
      # Health check configuration for vLLM
      alb.ingress.kubernetes.io/healthcheck-path: /health  # vLLM standard health endpoint
      alb.ingress.kubernetes.io/healthcheck-port: traffic-port #  router service port
      alb.ingress.kubernetes.io/healthcheck-protocol: HTTP
      alb.ingress.kubernetes.io/success-codes: "200-299"
    hosts:
#     - host:  vllm-api.com  # Replace with your domain
      - paths:
          - path: /
            pathType: Prefix

# Optional: TLS configuration
  # tls:
  #   - secretName: vllm-tls-secret
  #     hosts:
  #       - vllm-api.yourdomain.com
