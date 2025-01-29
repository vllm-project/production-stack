# Observability dashboard

![image](https://github.com/user-attachments/assets/225feb01-ac0f-4bf9-9da3-7bf955b2aa56)

## Deploy the observability stack

The observability stack is based on [kube-prom-stack](https://github.com/prometheus-community/helm-charts/blob/main/charts/kube-prometheus-stack/README.md).

To launch the observability stack:

```bash
sudo bash install.sh
```

After installing, the dashboard can be accessed through the service `service/kube-prom-stack-grafana` in the `monitoring` namespace.

## Access the Grafana dashboard

Forward the Grafana dashboard port to the local node-port

```bash
sudo kubectl --namespace monitoring port-forward svc/kube-prom-stack-grafana 3000:80 --address 0.0.0.0
```

Open the webpage at `http://<IP of your node>:3000` to access the Grafana web page. The default user name is `admin` and the password can be configured in `values.yaml` (default is `prom-operator`).

Import the dashboard using the `vllm-dashboard.json` in this folder.
