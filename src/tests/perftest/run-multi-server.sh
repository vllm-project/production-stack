#!/bin/bash

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 <number of servers> <tokens/req/sec>"
    exit 1
fi

for i in $(seq 1 "$1"); do
    python3 ./fake-openai-server.py --port "900$i" --speed "$2" &
done
