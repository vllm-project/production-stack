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
  - name: "tinyllama-gpu"
    repository: "vllm/vllm-openai"
    tag: "v0.8.5.post1"
    modelURL: "/data/models/tinyllama"
    replicaCount: 1
    requestCPU: 1
    requestMemory: "2Gi"
    requestGPU: 1  # requestGPUType: "nvidia.com/mig-4g.71gb" (MIG partitions) ! use with use resources:
    limitCPU: 2
    limitMemory: "12Gi"
    pvcStorage: "20Gi"
    storageClass: "shared-vast"  # Coreweave default storage class
    vllmConfig:
      enableChunkedPrefill: true
      enablePrefixCaching: true
      dtype:  "bfloat16"  # Changed from "bfloat16" not supported by Tesla T4 GPU (compute capability 7.5)
      extraArgs:
        - "--disable-log-requests"
        - "--gpu-memory-utilization=0.8"  # GPU-specific optimization
    env: []        # NEW: CPU env vars removed
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

 # GPT-OSS-20B
  - name: "gpt-oss-20b"
    repository: "vllm/vllm-openai"
    tag: "v0.15.1"
    modelURL: "/data/models/gpt-oss-20b"
    replicaCount: 1
    requestCPU: 8
    requestMemory: "64Gi"
    requestGPU: 1
    limitCPU: 16
    limitMemory: "128Gi"
    pvcStorage: "80Gi"
    storageClass: "shared-vast"
    vllmConfig:
      enableChunkedPrefill: true
      enablePrefixCaching: true
      dtype: "bfloat16"
      extraArgs:
        - "--disable-log-requests"
        - "--gpu-memory-utilization=0.9"
    initContainer:
      name: downloader
      image: python:3.11-slim
      command: ["/bin/sh", "-c"]
      args:
        - |
          pip install --no-cache-dir --timeout=300 "huggingface_hub" &&
          hf download openai/gpt-oss-20b \
            --local-dir /data/models/gpt-oss-20b
      env:
        - name: HUGGING_FACE_HUB_TOKEN
          valueFrom:
            secretKeyRef:
              name: hf-token-secret
              key: token
      resources:
        requests:
          cpu: "8"
          memory: "16Gi"
        limits:
          cpu: "16"
          memory: "32Gi"
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
    className: "traefik"  #  Use Traefik ingress controller
    annotations:
      # TLS/SSL configuration with cert-manager
      cert-manager.io/cluster-issuer: ${issuer_name}
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
