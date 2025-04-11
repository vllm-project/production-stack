# Integrating the Disaggregated QoE Router

This guide explains how to integrate the Disaggregated QoE Router into your existing vLLM router infrastructure. This implementation separates prefill and decoding phases of LLM inference, using dedicated optimized endpoints for each phase.

## 1. Prerequisites

- Existing vLLM router implementation
- Multiple vLLM endpoints with some optimized for prefill and others for decoding
- Python 3.7+

## 2. Integration Steps

### 2.1 Add Router Implementation Files

1. Copy the `disaggregated_qoe_router.py` file to your `src/vllm_router/routers/` directory
2. Copy the `test_disaggregated_qoe_router.py` file to your `src/tests/` directory

### 2.2 Update Router Enum

Modify the `RoutingLogic` enum in `src/vllm_router/routers/routing_logic.py`:

```python
class RoutingLogic(str, enum.Enum):
    ROUND_ROBIN = "roundrobin"
    SESSION_BASED = "session"
    QOE_CENTRIC = "qoe_centric"
    DISAGGREGATED_QOE = "disaggregated_qoe"
```

### 2.3 Update Router Initialization

Modify the `initialize_routing_logic` function in `src/vllm_router/routers/routing_logic.py`:

```python
def initialize_routing_logic(
    routing_logic: RoutingLogic, *args, **kwargs
) -> RoutingInterface:
    if routing_logic == RoutingLogic.ROUND_ROBIN:
        logger.info("Initializing round-robin routing logic")
        return RoundRobinRouter()
    elif routing_logic == RoutingLogic.SESSION_BASED:
        logger.info(f"Initializing session-based routing logic with kwargs: {kwargs}")
        return SessionRouter(kwargs.get("session_key"))
    elif routing_logic == RoutingLogic.QOE_CENTRIC:
        logger.info(f"Initializing QoE-centric routing logic with kwargs: {kwargs}")
        return QoECentricRouter(
            priority_header=kwargs.get("priority_header", "x-request-priority"),
            expected_output_len_header=kwargs.get("expected_output_len_header", "x-expected-output-tokens"),
            sla_header=kwargs.get("sla_header", "x-sla-target-ms")
        )
    elif routing_logic == RoutingLogic.DISAGGREGATED_QOE:
        logger.info(f"Initializing disaggregated QoE routing logic with kwargs: {kwargs}")
        from vllm_router.routers.disaggregated_qoe_router import DisaggregatedQoERouter
        return DisaggregatedQoERouter(
            prefill_tag=kwargs.get("prefill_tag", "prefill"),
            decoding_tag=kwargs.get("decoding_tag", "decoding"),
            priority_header=kwargs.get("priority_header", "x-request-priority"),
            expected_output_len_header=kwargs.get("expected_output_len_header", "x-expected-output-tokens"),
            sla_header=kwargs.get("sla_header", "x-sla-target-ms")
        )
    else:
        raise ValueError(f"Invalid routing logic {routing_logic}")
```

### 2.4 Update the Router Reconfiguration

Update the `reconfigure_routing_logic` function to include the new router:

```python
def reconfigure_routing_logic(
    routing_logic: RoutingLogic, *args, **kwargs
) -> RoutingInterface:
    # Remove the existing routers from the singleton registry
    from vllm_router.routers.disaggregated_qoe_router import DisaggregatedQoERouter
    for cls in (SessionRouter, RoundRobinRouter, QoECentricRouter, DisaggregatedQoERouter):
        if cls in SingletonABCMeta._instances:
            del SingletonABCMeta._instances[cls]
    return initialize_routing_logic(routing_logic, *args, **kwargs)
```

### 2.5 Update the Router Getter

Update the `get_routing_logic` function:

```python
def get_routing_logic() -> RoutingInterface:
    # Look up in our singleton registry which router (if any) has been created.
    from vllm_router.routers.disaggregated_qoe_router import DisaggregatedQoERouter
    for cls in (SessionRouter, RoundRobinRouter, QoECentricRouter, DisaggregatedQoERouter):
        if cls in SingletonABCMeta._instances:
            return cls()
    raise ValueError("The global router has not been initialized")
```

## 3. Request Lifecycle Tracking

### 3.1 Add Request Completion Hook

Update your request handler to call the `on_request_complete` method when a request completes:

```python
# In your request completion handler
from vllm_router.routers.routing_logic import get_routing_logic, RoutingLogic
from vllm_router.routers.disaggregated_qoe_router import DisaggregatedQoERouter

def on_request_done(request_id, success=True):
    router = get_routing_logic()
    if isinstance(router, DisaggregatedQoERouter):
        router.on_request_complete(request_id, success)
```

### 3.2 Add Request ID Extraction

Ensure your request handler extracts and propagates the request ID between prefill and decoding phases:

```python
# Extract request ID from incoming request
request_id = request.headers.get("x-request-id")
if not request_id:
    request_id = f"req_{int(time.time() * 1000)}_{id(request) % 10000}"

# Add request ID to outgoing requests
headers["x-request-id"] = request_id
```

## 4. Endpoint Configuration

### 4.1 Tag Your Endpoints

Ensure your endpoints are properly tagged for the router to identify them:

1. **Prefill-optimized endpoints** should include "prefill" in their URL or name:
   - `http://vllm-prefill-1.example.com`
   - `http://vllm-prefill-2.example.com`

2. **Decoding-optimized endpoints** should include "decoding" in their URL or name:
   - `http://vllm-decoding-1.example.com`
   - `http://vllm-decoding-2.example.com`

### 4.2 Endpoint Metadata (Optional)

For more explicit tagging, you can add metadata to your `EndpointInfo` objects:

```python
endpoints = [
    EndpointInfo(
        url="http://vllm-1.example.com",
        metadata={"tags": ["prefill"], "priority": 1}
    ),
    EndpointInfo(
        url="http://vllm-2.example.com",
        metadata={"tags": ["decoding"], "priority": 1}
    )
]
```

## 5. Activate the Router

Update your configuration to use the disaggregated QoE router:

```python
# In your configuration file or startup code
router = initialize_routing_logic(
    RoutingLogic.DISAGGREGATED_QOE,
    prefill_tag="prefill",
    decoding_tag="decoding",
    priority_header="x-request-priority",
    expected_output_len_header="x-expected-output-tokens",
    sla_header="x-sla-target-ms"
)
```

## 6. Monitoring Integration

### 6.1 Add Phase-Specific Metrics

Extend your metrics collection to track phase-specific performance:

```python
# Add Prometheus metrics for prefill and decoding phases
from prometheus_client import Gauge

prefill_latency = Gauge('prefill_latency_seconds', 'Prefill phase latency in seconds', ['endpoint'])
decoding_throughput = Gauge('decoding_throughput_tokens_per_second', 'Decoding phase throughput', ['endpoint'])
end_to_end_latency = Gauge('end_to_end_latency_seconds', 'End-to-end request latency', ['priority'])
```

### 6.2 Update Metrics Endpoint

Extend your metrics endpoint to include the new measurements:

```python
@app.get("/metrics")
async def metrics():
    # Existing metrics code...

    # Add phase-specific metrics
    router = get_routing_logic()
    if isinstance(router, DisaggregatedQoERouter):
        for request_id, data in router.request_tracking.items():
            if "prefill_start_time" in data and "decoding_start_time" in data:
                prefill_time = data["decoding_start_time"] - data["prefill_start_time"]
                prefill_endpoint = data.get("prefill_endpoint", "unknown")
                prefill_latency.labels(endpoint=prefill_endpoint).set(prefill_time)

    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
```

## 7. Testing

### 7.1 Unit Tests

Run the provided unit tests:

```bash
python -m pytest src/tests/test_disaggregated_qoe_router.py -v
```

### 7.2 Integration Test

Create a simple test script to verify the router works with your infrastructure:

```python
# test_router_integration.py
import requests

# Test prefill request
prefill_response = requests.post(
    "http://your-router-endpoint/v1/completions",
    json={"model": "your-model", "messages": [{"role": "user", "content": "Hello"}]},
    headers={"x-request-id": "test-req-1", "x-request-priority": "1"}
)
print(f"Prefill response from: {prefill_response.headers.get('x-served-by')}")

# Test decoding request
decoding_response = requests.post(
    "http://your-router-endpoint/v1/completions",
    json={
        "model": "your-model",
        "messages": [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"}
        ]
    },
    headers={"x-request-id": "test-req-2", "x-request-priority": "1"}
)
print(f"Decoding response from: {decoding_response.headers.get('x-served-by')}")
```

## 8. Troubleshooting

### Common Issues

1. **Endpoints not being correctly tagged**
   - Check endpoint URLs and metadata
   - Verify that `_filter_endpoints_by_tag` is correctly identifying endpoints

2. **Request phase not correctly identified**
   - Debug the `_is_prefill_request` method
   - Check the format of your request JSON payloads

3. **Request tracking data not being maintained**
   - Ensure request IDs are consistent between prefill and decoding phases
   - Verify that `on_request_complete` is being called

4. **Performance not improving**
   - Check that your prefill and decoding endpoints are actually optimized for their respective phases
   - Verify that the router is correctly choosing endpoints based on their scores
