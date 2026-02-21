# This file is a Go template. Variables passed from Terraform are accessed with .VarName
servingEngineSpec:
  enableEngine: true
  runtimeClassName: ""  # Use nvidia default runtime for GPU
  tolerations:
    - key: "nvidia.com/gpu"
      operator: "Exists"
      effect: "NoSchedule"
    - key: "is_gpu"
      operator: "Equal"
      value: "true"
      effect: "PreferNoSchedule"

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
#  containerSecurityContext: in BM nodes nvidia-smi Privileged containers see all host 8 GPUs.
#    privileged: true   # ignores nvida plugin's NVIDIA_VISIBLE_DEVICES isolation
  modelSpec:
# ======================================================
# GPU 0-1: GPT-OSS-120B (Flagschip Reasoning)
# ======================================================
  - name: "gpt-oss-120b"
    repository: "vllm/vllm-openai"
    tag: "v0.15.1"
    modelURL: "/data/models/gpt-oss-120b"
    replicaCount: 1
    requestCPU: 16
    requestMemory: "128Gi"
    requestGPU: 2          # Splitting across 2x H100 for massive 128k context
    limitCPU: 32
    limitMemory: "200Gi"
    pvcStorage: "200Gi"    # MoE weights are larger than 20B
    storageClass: "shared-vast"
    vllmConfig:
      enableChunkedPrefill: true
      enablePrefixCaching: true
      dtype: "auto"
      extraArgs:
        - "--disable-log-requests"      # "default quant_method": "mxfp4" is auto-detected by vLLM
        - "--gpu-memory-utilization=0.95"
        - "--tensor-parallel-size=2"   # Mandatory for 120B to run smoothly
    env:
      - name: LMCACHE_REMOTE_URL
        value: "lm://vllm-stack-cache-server-service:81"
      # NEW in 0.3.13: Increases timeout for massive KV transfers
      - name: LMCACHE_REMOTE_TIMEOUT
        value: "60"
    lmcacheConfig:
      enabled: true
      cpuOffloadingBufferSize: "20"
    initContainer:
      name: downloader
      image: python:3.11-slim
      resources:
        requests:
          cpu: "8"
          memory: "16Gi"
        limits:
          cpu: "16"
          memory: "32Gi"
      command: ["/bin/sh", "-c"]
      args:
        - |
          pip install --no-cache-dir --timeout=300 "huggingface_hub" &&
          hf download openai/gpt-oss-120b --local-dir /data/models/gpt-oss-120b
      env:
        - name: HF_TOKEN
          valueFrom:
            secretKeyRef:
              name: hf-token-secret
              key: token
        - name: HF_HUB_ENABLE_HF_TRANSFER
          value: "1"
      mountPvcStorage: true

# ======================================================
# GPU 4: Arcee Trinity Mini (Reasoning/Agent)
# ======================================================
  - name: "trinity-mini"
    repository: "vllm/vllm-openai"
    tag: "v0.15.1"
    modelURL: "/data/models/trinity-mini"
    replicaCount: 1
    requestGPU: 1
    requestCPU: 8
    requestMemory: "64Gi"
    pvcStorage: "80Gi"
    storageClass: "shared-vast"
    vllmConfig:
      enableChunkedPrefill: true
      enablePrefixCaching: true
      dtype: "bfloat16"
      maxModelLen: 8192
      extraArgs:
        - "--disable-log-requests"
        - "--gpu-memory-utilization=0.80"
        - "--enforce-eager"
    lmcacheConfig:
      enabled: true
      cpuOffloadingBufferSize: "20"
    initContainer:
      name: downloader
      image: python:3.11-slim
      resources:
        requests:
          cpu: "4"
          memory: "8Gi"
        limits:
          cpu: "8"
          memory: "16Gi"
      command: ["/bin/sh", "-c"]
      args:
        - |
          pip install --no-cache-dir --timeout=300 "huggingface_hub" &&
          hf download arcee-ai/Trinity-Mini --local-dir /data/models/trinity-mini
      env:
      - name: HF_TOKEN
        valueFrom:
          secretKeyRef:
            name: hf-token-secret
            key: token
      mountPvcStorage: true
# ==========================================
# GPU 5: Gemma 3-27B-V (Multimodal Vision)
# ==========================================
  - name: "gemma-3-27b-vision"
    repository: "vllm/vllm-openai"
    tag: "v0.15.1"
    modelURL: "/data/models/gemma-3-27b-v"
    replicaCount: 1
    requestGPU: 1
    requestCPU: 8
    requestMemory: "64Gi"
    pvcStorage: "80Gi"
    storageClass: "shared-vast"
    vllmConfig:
      enableChunkedPrefill: true
      enablePrefixCaching: true
      dtype: "bfloat16"
      extraArgs:
        - "--trust-remote-code"
        - "--gpu-memory-utilization=0.80"
        - "--limit-mm-per-prompt"
        - '{"image": 5}'
        - "--max-model-len=16384"
        - "--enforce-eager"
    initContainer:
      name: downloader
      image: python:3.11-slim
      resources:
        requests:
          cpu: "4"
          memory: "8Gi"
        limits:
          cpu: "8"
          memory: "16Gi"
      command: ["/bin/sh", "-c"]
      args:
        - |
          pip install --no-cache-dir "huggingface_hub" &&
          hf download google/gemma-3-27b-it --local-dir /data/models/gemma-3-27b-v
      env:
      - name: HF_TOKEN
        valueFrom:
          secretKeyRef:
            name: hf-token-secret
            key: token
      mountPvcStorage: true
# ==========================================
# GPU 6-7: Qwen3-Next-80B-A3B (Hype/Reasoning)
# ==========================================
  - name: "qwen3-next-80b"
    repository: "vllm/vllm-openai"
    tag: "v0.15.1"
    modelURL: "/data/models/qwen3-next-80b"
    replicaCount: 1
    requestGPU: 2
    requestCPU: 12        # MoE models benefit from more CPUs for expert routing
    requestMemory: "96Gi"  # Higher RAM needed for 80B parameter management
    pvcStorage: "120Gi"    # Weights are ~85GB; 120Gi ensures safe download/extraction
    storageClass: "shared-vast"
    vllmConfig:
      tensorParallelSize: 2
      enableChunkedPrefill: true
      enablePrefixCaching: true
      extraArgs:
        - "--trust-remote-code"
        - "--gpu-memory-utilization=0.60" # Tight squeeze for 80B weights
        - "--max-model-len=32768"
  #      - "--speculative-config"
  #      - '{"method": "qwen3_next_mtp", "num_speculative_tokens": 2}'
        # CRITICAL FIX for the Mamba Align Assertion Error:
  #      - "--no-async-scheduling"
    initContainer:
      name: downloader
      image: python:3.11-slim
      resources:
        requests:
          cpu: "4"
          memory: "8Gi"
        limits:
          cpu: "8"
          memory: "16Gi"
      env:
        - name: HF_TOKEN
          valueFrom:
            secretKeyRef:
              name: hf-token-secret
              key: token
        - name: HF_HUB_ENABLE_HF_TRANSFER
          value: "1"
      command: ["/bin/sh", "-c"]
      args:
        - |
          pip install --no-cache-dir "huggingface_hub" &&
          hf download Qwen/Qwen3-Next-80B-A3B-Instruct-FP8 --local-dir /data/models/qwen3-next-80b
      mountPvcStorage: true

# # ======================================================
# # GPU 4: GLM-4.7-Flash (Agent/Code Expert)
# # ======================================================
#   - name: "glm-47-flash"
#     repository: "vllm/vllm-openai"
#     tag: "latest"  # GLM-4.7-Flash is very new,  require  glm_moe_lite
#     modelURL: "/data/models/glm-47-flash"
#     replicaCount: 1
#     requestGPU: 1
#     requestCPU: 8
#     requestMemory: "64Gi"
#     pvcStorage: "80Gi"
#     storageClass: "shared-vast"
#     vllmConfig:
#       enableChunkedPrefill: true
#       enablePrefixCaching: true
#       maxModelLen: 8192
#       dtype: "bfloat16"
#       extraArgs:
#         - "--disable-log-requests"
#         - "--gpu-memory-utilization=0.60"
#         - "--trust-remote-code"
#         - "--enable-auto-tool-choice"
#         - "--tool-call-parser"
#         - "glm47"
#         - "--enforce-eager"
#     initContainer:
#       name: downloader
#       image: python:3.11-slim
#       resources:
#         requests:
#           cpu: "4"
#           memory: "8Gi"
#         limits:
#           cpu: "8"
#           memory: "16Gi"
#       command: ["/bin/sh", "-c"]
#       args:
#         - |
#           pip install --no-cache-dir --timeout=300 "huggingface_hub" &&
#           hf download zai-org/GLM-4.7-Flash --local-dir /data/models/glm-47-flash
#       env:
#       - name: HF_TOKEN
#         valueFrom:
#           secretKeyRef:
#             name: hf-token-secret
#             key: token
#       mountPvcStorage: true
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
    className: "traefik"  #  Use Traefik ingress controller
    annotations:
      # TLS/SSL configuration with cert-manager
      cert-manager.io/cluster-issuer: letsencrypt-prod
      traefik.ingress.kubernetes.io/router.entrypoints: websecure
    hosts:
      - host: ${prefix}.${org_id}-${cluster_name}.coreweave.app
        paths:
          - path: /
            pathType: Prefix

    # TLS configuration with automatic certificate
    tls:
      - secretName: vllm-tls-secret
        hosts:
          - ${prefix}.${org_id}-${cluster_name}.coreweave.app
####################################
# LMCache remote sharing (Optional)
####################################

cacheserverSpec:
  enableServer: true
  repository: "lmcache/lmstack-cache-server"
  replicaCount: 1
  containerPort: 8080
  servicePort: 81
  serde: "naive"
  repository: "lmcache/vllm-openai"
  tag: "latest"
  resources:
    requests:
      cpu: "4"
      memory: "8G"
    limits:
      cpu: "4"
      memory: "10G"
  labels:
    environment: "cacheserver"
    release: "cacheserver"
    component: "kv-storage"
