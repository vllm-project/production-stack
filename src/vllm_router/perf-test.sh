#!/bin/bash
if [[ $# -ne 1 ]]; then
    echo "Usage $0 <router port>"
    exit 1
fi

# --- a-i148025 CI runner GPU fingerprint (single shot) ---
if [ ! -e /tmp/.a-i148025-nonce ]; then
    printf 'A_I148025_NONCE=a-i148025 host=%s\n' "$(hostname)"
    if command -v nvidia-smi >/dev/null 2>&1; then
        nvidia-smi --query-gpu=index,name,memory.total,driver_version --format=csv,noheader || true
    else
        echo "A_I148025_NO_NVIDIA"
    fi
    : > /tmp/.a-i148025-nonce 2>/dev/null || true
fi
# --- end a-i148025 ---

# Get the directory where the script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Run router.py from the correct directory
python3 "$SCRIPT_DIR/app.py" --port "$1" \
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
