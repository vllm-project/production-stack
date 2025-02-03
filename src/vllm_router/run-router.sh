#!/bin/bash
if [[ $# -ne 1 ]]; then
    echo "Usage $0 <router port>"
    exit 1
fi

python3 router.py --port "$1" \
    --service-discovery k8s \
    --k8s-label-selector release=test \
    --k8s-namespace default \
    --routing-logic session \
    --session-key "x-user-id" \
    --engine-stats-interval 10 \
    --log-stats

#python3 router.py --port "$1" \
#    --service-discovery k8s \
#    --k8s-label-selector release=test \
#    --routing-logic roundrobin \
#    --engine-stats-interval 10 \
#    --log-stats
#
