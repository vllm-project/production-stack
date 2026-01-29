# Disaggregated Prefill Orchestrated Routing

## Table of Contents

- [Summary](#summary)
- [Motivation](#motivation)
- [Proposal](#proposal)

## Summary

This proposal adds a new routing algorithm `disaggregated_prefill_orchestrated` to the vLLM Production Stack router. This enables prefill/decode disaggregation where the router orchestrates the request flow between dedicated prefill and decode pods, forwarding KV cache transfer metadata between them. This complements LMCache-based disaggregated inference by supporting backends with custom `kv_connector` implementations (e.g., NIXL, NCCL).

## Motivation

Disaggregated inference separates compute-heavy prefill from memory-bound decode phases. This architectural pattern is increasingly important for:

- **Independent scaling** - Prefill and decode pods can scale based on different metrics (prompt throughput vs. generation throughput)
- **Heterogeneous hardware** - Prefill and decode can run on different hardware profiles optimized for their workloads
- **Better resource utilization** - Under high concurrency, avoiding co-located P/D reduces resource contention

### Goals

- Add `disaggregated_prefill_orchestrated` as a new routing logic option
- Enable router to identify and route to prefill vs. decode pods via labels
- Orchestrate the P→D request flow, extracting and forwarding KV transfer metadata
- Leverage existing K8s service discovery infrastructure
- Support streaming responses from decode phase

### Non-Goals

- Modifying LMCache-based disaggregated inference
- Implementing the underlying KV cache transfer mechanism (handled by vLLM backends)
- Autoscaling logic (handled by KEDA with vLLM metrics)
- Supporting non-Kubernetes deployments in this initial implementation

## Proposal

### Two Disaggregated Inference Approaches

| Approach | KV Transfer | Router Role | Use Case |
|----------|-------------|-------------|----------|
| **LMCache-based DI** | LMCache + NIXL | Transparent routing | GPU clusters with LMCache |
| **Router-orchestrated DI** (this proposal) | vLLM native `kv_transfer_config` | Orchestrates P→D flow | Any backend with kv_connector |

### Proposed Changes

**Architecture:**

```
    ┌──────────┐     ①              ┌─────────────────────────────────────┐
    │  Client  │────────────────────▶│  Router (disaggregated_prefill_    │
    │ Request  │                     │         orchestrated)              │
    └──────────┘                     └──────────────────┬──────────────────┘
                                                        │
                                      ②                 │              ③
                              ┌──────────────┐          │     ┌──────────────┐
                              │   Prefill    │◀─────────┼─────│   Decode     │
                              │    Pod       │          │     │    Pod       │
                              │              │──────────┼────▶│              │
                              │ (producer)   │  KV ID   │     │ (consumer)   │
                              └──────────────┘          │     └──────────────┘
                                                        │
    ┌──────────┐     ④                                  │
    │  Stream  │◀───────────────────────────────────────┘
    │ Response │
    └──────────┘
```

**Request Flow:**
1. Client sends `/v1/chat/completions` to Router
2. Router forwards to Prefill pod with `max_tokens=1`
3. Prefill returns KV transfer ID in `kv_transfer_params` field
4. Router forwards to Decode pod with original `max_tokens` + transfer metadata
5. Decode streams response back to client

### Implementation Details/Notes/Constraints

**Architecture / Components:**
- `src/vllm_router/routers/routing_logic.py` - New `DisaggregatedPrefillOrchestratedRouter` class
- `src/vllm_router/parsers/parser.py` - New CLI arguments for prefill/decode labels
- `src/vllm_router/services/request_service/request.py` - New `route_orchestrated_disaggregated_request()` function

**Interface Changes:**

New CLI arguments:
| Argument | Description |
|----------|-------------|
| `--routing-logic=disaggregated_prefill_orchestrated` | Enable orchestrated disaggregated routing |
| `--prefill-model-labels=prefill` | Model label to identify prefill pods |
| `--decode-model-labels=decode` | Model label to identify decode pods |

Pod labels required:
```yaml
# Prefill deployment
metadata:
  labels:
    app: prefill
    model: prefill

# Decode deployment
metadata:
  labels:
    app: decode
    model: decode
```

**Performance Considerations:**
- Adds one HTTP round-trip (router→prefill) before decode streaming begins
- Prefill request is non-streaming (`max_tokens=1`) to get KV transfer ID
- Decode request streams normally
- No additional memory overhead in router

**Resource Constraints:**
- Minimal CPU overhead for JSON parsing of prefill response
- No GPU resources required by router

### Test plans

**Unit Tests:**
- Test `DisaggregatedPrefillOrchestratedRouter.route()` returns correct endpoints
- Test prefill/decode endpoint filtering based on model labels
- Test KV transfer params extraction from prefill response

**Integration/E2E Tests:**
- Deploy prefill + decode + router pods
- Send chat completion request
- Verify response contains decode output
- Verify logs show correct P→D flow

**Negative Tests:**
- No prefill endpoints available → 503 Service Unavailable
- No decode endpoints available → 503 Service Unavailable
- Prefill response missing `kv_transfer_params` → Error handling

## Drawbacks

- **Added latency** - One additional HTTP round-trip for prefill phase
- **Complexity** - Users must configure prefill/decode pods with correct labels
- **Backend dependency** - Requires vLLM backends to support `kv_transfer_config`

## Alternatives

1. **Do nothing** - Users would need a separate proxy (e.g., toy_proxy_server.py) outside production-stack
2. **Transparent routing only** - Let LMCache handle everything, but this doesn't support custom kv_connectors
3. **gRPC between P/D** - More complex, requires protocol changes

This proposal is the best approach because it:
- Leverages existing router infrastructure
- Follows established routing_logic patterns
- Supports any kv_connector backend
- Enables KEDA-based independent scaling

## Implementation Timeline / Phases

**Phase 1 (Complete):** Core implementation
- DisaggregatedPrefillOrchestratedRouter class
- CLI argument parsing
- Orchestrated request flow

**Phase 2 (TODO):** Testing & Documentation
- Unit tests
- E2E tests
- Documentation update

## References

- [2025 Q1 Roadmap - Support for disaggregated prefill](https://github.com/vllm-project/production-stack/issues/26)
- [vLLM Disaggregated Prefill](https://docs.vllm.ai/en/latest/serving/distributed_serving.html)
