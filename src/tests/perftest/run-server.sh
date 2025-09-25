#!/bin/bash

if [[ $# -eq 0 ]] ; then
    echo 'Usage: ./run-server.sh <port> <speed>'
    exit 1
fi

python3 ./fake-openai-server.py --port "$1" --speed "$2"
