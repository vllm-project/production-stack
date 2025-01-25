#!/bin/bash
if [[ $# -ne 1 ]]; then
    echo "Usage $0 <router port>"
    exit 1
fi

python3 router.py --port $1 \
    --service-discovery static \
    --static-backends "http://localhost:9004,http://localhost:9001,http://localhost:9002,http://localhost:9003" \
    --static-models "fake_model_name,fake_model_name,fake_model_name,fake_model_name" \
    --engine-stats-interval 10 \
    --log-stats \
    --routing-logic session \
    --session-key "x-user-id" 

    #--routing-logic roundrobin

    #--routing-logic session \
    #--session-key "x-user-id" \
