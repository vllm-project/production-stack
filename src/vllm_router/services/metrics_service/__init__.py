from prometheus_client import Gauge

# --- Prometheus Gauges ---
# Existing metrics
num_requests_running = Gauge(
    "vllm:num_requests_running", "Number of running requests", ["server"]
)
num_requests_waiting = Gauge(
    "vllm:num_requests_waiting", "Number of waiting requests", ["server"]
)
current_qps = Gauge("vllm:current_qps", "Current Queries Per Second", ["server"])
avg_decoding_length = Gauge(
    "vllm:avg_decoding_length", "Average Decoding Length", ["server"]
)
num_prefill_requests = Gauge(
    "vllm:num_prefill_requests", "Number of Prefill Requests", ["server"]
)
num_decoding_requests = Gauge(
    "vllm:num_decoding_requests", "Number of Decoding Requests", ["server"]
)

# New metrics per dashboard update
healthy_pods_total = Gauge(
    "vllm:healthy_pods_total", "Number of healthy vLLM pods", ["server"]
)
avg_latency = Gauge(
    "vllm:avg_latency", "Average end-to-end request latency", ["server"]
)
avg_itl = Gauge("vllm:avg_itl", "Average Inter-Token Latency", ["server"])
num_requests_swapped = Gauge(
    "vllm:num_requests_swapped", "Number of swapped requests", ["server"]
)
