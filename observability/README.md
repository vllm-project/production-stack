# Observability dashboard

<p align="center">
  <img src="https://github.com/user-attachments/assets/05766673-c449-4094-bdc8-dea6ac28cb79" alt="Grafana dashboard to monitor the deployment" width="80%"/>
</p>

## Deploy the observability stack

The observability stack is based on [kube-prom-stack](https://github.com/prometheus-community/helm-charts/blob/main/charts/kube-prometheus-stack/README.md).

To launch the observability stack:

Make sure to have:

- A running Kubernetes (K8s) environment with GPUs
  - Run `cd utils && bash install-minikube-cluster.sh`
  - Or follow our [tutorial](tutorials/00-install-kubernetes-env.md)

After that you can run:

```bash
sudo bash install.sh
```

After installing, the dashboard can be accessed through the service `service/kube-prom-stack-grafana` in the `monitoring` namespace.

## Access the Grafana & Prometheus dashboard

Forward the Grafana dashboard port to the local node-port

```bash
sudo kubectl --namespace monitoring port-forward svc/kube-prom-stack-grafana 3000:80 --address 0.0.0.0
```

Forward the Prometheus dashboard

```bash
sudo kubectl --namespace monitoring port-forward prometheus-kube-prom-stack-kube-prome-prometheus-0 9090:9090
```

Open the webpage at `http://<IP of your node>:3000` to access the Grafana web page. The default user name is `admin` and the password can be configured in `values.yaml` (default is `prom-operator`).

Import the dashboard using the `vllm-dashboard.json` in this folder.
