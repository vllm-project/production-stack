
apiVersion: v1
clusters:
- cluster:
    certificate-authority-data: ${cluster_ca}
    server: ${cluster_endpoint}
  name: ${cluster_name}
contexts:
- context:
    cluster: ${cluster_name}
    user: ${cluster_name}
  name: ${cluster_name}
current-context: ${cluster_name}
kind: Config
users:
- name: ${cluster_name}
  user:
    exec:
      apiVersion: client.authentication.k8s.io/v1
      command: bash
      interactiveMode: IfAvailable
      args:
        - -c
        - |
          tok=$(nebius iam get-access-token --format json%{ if profile != "" } --profile ${profile}%{ endif });
          jq -n --arg token "$tok" '{apiVersion: "client.authentication.k8s.io/v1", kind: "ExecCredential", status: {token: $token}}'
