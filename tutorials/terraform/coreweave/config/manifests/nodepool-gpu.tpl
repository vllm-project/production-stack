apiVersion: compute.coreweave.com/v1alpha1
kind: NodePool
metadata:
  name: ${nodepool_name}
spec:
  instanceType: ${instance_type}
  computeClass: default

  autoscaling: ${autoscaling}
  targetNodes: ${target_nodes}
  minNodes: ${min_nodes}
  maxNodes: ${max_nodes}

  lifecycle:
    scaleDownStrategy: ${scale_down}
    disableUnhealthyNodeEviction: ${disable_evict}

  nodeLabels:
%{ for key, value in node_labels ~}
    ${key}: "${value}"
%{ endfor ~}

  nodeTaints:
%{ for taint in node_taints ~}
    - key: "${taint.key}"
      value: "${taint.value}"
      effect: "${taint.effect}"
%{ endfor ~}
