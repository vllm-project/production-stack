from prometheus_client import Counter, Gauge

# --- Prometheus Gauges ---
# Existing metrics
num_requests_running = Gauge(
    "vllm:num_requests_running", "Number of running requests", ["server"]
)
num_requests_waiting = Gauge(
    "vllm:num_requests_waiting", "Number of waiting requests", ["server"]
)
gpu_prefix_cache_hit_rate = Gauge(
    "vllm:gpu_prefix_cache_hit_rate",
    "GPU Prefix Cache Hit Rate",
    ["server"],
)
gpu_prefix_cache_hits_total = Gauge(
    "vllm:gpu_prefix_cache_hits_total",
    "Total GPU Prefix Cache Hits",
    ["server"],
)
gpu_prefix_cache_queries_total = Gauge(
    "vllm:gpu_prefix_cache_queries_total",
    "Total GPU Prefix Cache Queries",
    ["server"],
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
num_incoming_requests_total = Counter(
    "vllm:num_incoming_requests",
    "Total valid incoming requests to router (including when no backends available).",
    ["model"],
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

# --- Model-level Metrics (labeled by server and model) ---
# Token usage metrics for monitoring throughput per model
input_tokens_total = Counter(
    "vllm:input_tokens_total",
    "Total input/prompt tokens processed",
    ["server", "model"],
)
output_tokens_total = Counter(
    "vllm:output_tokens_total",
    "Total output/completion tokens generated",
    ["server", "model"],
)

# Error metrics for monitoring reliability per model
request_errors_total = Counter(
    "vllm:request_errors_total",
    "Total request errors",
    ["server", "model", "error_type"],
)
