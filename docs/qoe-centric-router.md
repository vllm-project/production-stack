# QoE-Centric Router for LLM Inference Services

## Overview

The QoE-Centric (Quality of Experience) Router is an advanced request routing system designed to optimize user experience for LLM inference services. Unlike traditional routers that focus solely on system metrics like QPS or simple round-robin strategies, this router explicitly differentiates between the two distinct phases of LLM inference:

1. **Prefill Phase**: Initial token generation, requiring high computational resources and significantly impacting time-to-first-token (TTFT)
2. **Decoding Phase**: Subsequent token generation, requiring consistent performance for smooth streaming

By understanding these different phases and their unique requirements, the QoE-centric router makes intelligent routing decisions that improve perceived latency, throughput, and overall user satisfaction.

## Architecture

![QoE-Centric Router Architecture](https://mermaid.ink/img/pako:eNqFksFqwzAMhl_F-LRB8wA5DNrSHQbdbYd2h9aSE9HaFrYyKCHvPidpspXCfJH1S5-QZI3KOotKqJ2Z-F4jj4x2NBoTYczEdpM_SRKpAcNnxF76hn5HsMaB9WqPNsIYUbhZ97ClHowzB0-Jl8yTI6QI0-4VXLvMHvZo-wA9dQ3ckrJoZhiMTsJfp7oGO4FPPvM8ys_jEu9KrgXXF8cVXJcYKn_EHrWrFXTk6S3Qfw8fR5WN1mzS_JvzrG2ENiTSIu2LYStaOFnqUalS8EqvUYxeC-nQvnNPZlZ697fmFR9KRWWs94UgKZx7Ka3HnC6Fmjq8gNQFT1zfB53AXB5oWF4-AShHkTo?type=png)

### Components

1. **Router Core**: The central routing logic that calculates QoE-based costs and selects the optimal endpoint
2. **Request Analyzer**: Determines request characteristics including prefill/decoding phase and expected output length
3. **Performance Metrics System**: Tracks detailed phase-specific metrics for each endpoint
4. **Adaptive Parameter System**: Dynamically adjusts routing parameters based on system conditions
5. **QoE Cost Calculator**: Multi-factor scoring system that balances various aspects of user experience

## Implementation

The QoE-centric router extends the existing `RoutingInterface` and is fully compatible with the current routing framework:

```python
class QoECentricRouter(RoutingInterface):
    """
    Route requests using a QoE-centric approach that differentiates between
    prefill and decoding phases of LLM inference to optimize user experience.
    """
```

### Key Methods

- `route_request()`: Main entry point that calculates QoE costs and selects the optimal endpoint
- `_is_prefill_request()`: Determines if a request is in the prefill phase
- `_calculate_prefill_score()`: Calculates optimization score for prefill-specific characteristics
- `_calculate_decoding_score()`: Calculates optimization score for decoding-specific characteristics
- `_adapt_parameters()`: Dynamically adjusts scoring weights based on system conditions

### QoE Cost Function

The router uses a weighted multi-factor cost function:

```python
qoe_cost = (
    α * resource_cost +
    β * performance_cost +
    γ * reliability_cost +
    δ * priority_cost
)
```

Where:

- `resource_cost`: Considers GPU cache usage and request queue length
- `performance_cost`: Evaluates phase-specific metrics (TTFT for prefill, ITL for decoding)
- `reliability_cost`: Measures endpoint stability and uptime
- `priority_cost`: Adjusts based on request priority headers

## Configuration

The QoE-centric router can be configured with the following parameters:

| Parameter | Description | Default |
|-----------|-------------|---------|
| `priority_header` | HTTP header for request priority | `x-request-priority` |
| `expected_output_len_header` | HTTP header for expected output length | `x-expected-output-tokens` |
| `sla_header` | HTTP header for SLA target time | `x-sla-target-ms` |
| `target_ttft` | Target time to first token (ms) | 300 |
| `target_itl` | Target inter-token latency (ms) | 50 |
| `optimal_throughput` | Optimal tokens per second | 30 |

### Priority Levels

- **Priority 1**: High priority requests (e.g., premium users, critical applications)
- **Priority 2**: Medium priority requests (default)
- **Priority 3**: Low priority requests (e.g., batch processing, non-interactive)

## Benefits

### Improved User Experience

- **Faster TTFT**: By routing prefill requests to endpoints with optimal TTFT characteristics
- **Smoother Streaming**: By routing decoding requests to endpoints with better ITL performance
- **Priority-Based Routing**: Better service for high-priority requests and SLA compliance

### System Optimization

- **Better Resource Utilization**: By understanding the phase-specific resource needs
- **Adaptive Behavior**: Automatically adjusts to changing system conditions
- **Load Balancing**: Distributes load based on endpoint's phase-specific performance

### Comparison with Previous Routing Strategies

| Metric | Round-Robin | Session-Based | QoE-Centric |
|--------|-------------|---------------|-------------|
| TTFT | Variable | Consistent per session | Optimized |
| ITL | Variable | Consistent per session | Optimized |
| Resource Usage | Balanced | Session-biased | Phase-optimized |
| Priority Support | None | None | Full support |
| Adaptability | None | Limited | Automatic |

## Usage

### Basic Configuration

```python
from vllm_router.routers.routing_logic import RoutingLogic, initialize_routing_logic

# Initialize router in configuration
router = initialize_routing_logic(
    RoutingLogic.QOE_CENTRIC,
    priority_header="x-request-priority",
    expected_output_len_header="x-expected-output-tokens",
    sla_header="x-sla-target-ms"
)
```

### Request Headers

Client requests can include optional headers to influence routing decisions:

```yaml
GET /v1/completions
Host: api.example.com
Content-Type: application/json
x-request-priority: 1
x-expected-output-tokens: 2048
x-sla-target-ms: 500
```

### Monitoring

The router leverages existing metrics from `RequestStats` and `EngineStats` with a particular focus on:

- `ttft`: Time to first token (critical for prefill phase)
- `avg_itl`: Average inter-token latency (critical for decoding phase)
- `in_prefill_requests`: Number of requests in prefill phase
- `in_decoding_requests`: Number of requests in decoding phase
- `gpu_prefix_cache_hit_rate`: Cache hit rate (impacts prefill performance)

## Future Enhancements

1. **Multi-Stage Routing**: Routing a request to different endpoints for prefill and decoding phases
2. **Learning-Based Adaptation**: Using historical data to predict optimal routing decisions
3. **SLA Enforcement**: Strict enforcement of SLA guarantees for high-priority requests
4. **Endpoint Specialization**: Dedicating specific endpoints to prefill or decoding optimization
5. **Enhanced Prefill Detection**: More sophisticated detection of prefill vs. decoding requests
