installation:
  enabled: true
  kubernetesProvider: "EKS"
  cni:
    type: Calico
  calicoNetwork:
    bgp: "Disabled"
    ipPools:
      - cidr: "${pod_cidr}"
        encapsulation: VXLAN
        natOutgoing: Enabled
        nodeSelector: "all()"
  # Add this to ensure proper CNI takeover
  variant: "Calico"

# API server (sometimes needed for EKS)
apiServer:
  enabled: true
# everything you already had ↓
typha:
  enabled: true
  replicas: 1

prometheus:
  serviceMonitor:
    enabled: true
    namespace: monitoring

felixConfiguration:
  failsafeInboundHostPorts:  []
  failsafeOutboundHostPorts: []
# Additional Felix settings for hostNetwork
  useInternalDataplaneDriver: true
