# This file is a Go template. Variables passed from Terraform are accessed with .VarName
servingEngineSpec:
  enableEngine: true
  runtimeClassName: ""  # Use default runtime for CPU
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
    modelURL: "TinyLlama/TinyLlama-1.1B-Chat-v1.0"
    replicaCount: 1
    requestCPU: 1
    requestMemory: "2Gi"
    requestGPU: 0
    limitCPU: "2"
    limitMemory: "4Gi"
    pvcStorage: "10Gi"
    storageClass: "gp2"
    vllmConfig:
      dtype: "bfloat16"
      extraArgs:
        - "--device"
        - "cpu"
    env:
      - name: VLLM_CPU_KVCACHE_SPACE
        value: "1"
      - name: VLLM_CPU_OMP_THREADS_BIND
        value: "0-1"
      - name: HUGGING_FACE_HUB_TOKEN
        valueFrom:
          secretKeyRef:
            name: hf-token-secret
            key: token

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
