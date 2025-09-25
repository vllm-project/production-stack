#!/bin/bash
helm uninstall prometheus-adapter -n monitoring
helm uninstall -n monitoring kube-prom-stack
