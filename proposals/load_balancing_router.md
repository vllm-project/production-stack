# Add TimeTrackingRouter: QoE-driven endpoint routing balancing latency

## Table of Contents

* [Summary](#summary)
* [Motivation](#motivation)
* [Goals](#goals)
* [Non-Goals](#non-goals)
* [Proposal](#proposal)

  * [Proposed Changes](#proposed-changes)
  * [Implementation Details/Notes/Constraints](#implementation-detailsnotesconstraints)
  * [Test Plans](#test-plans)
* [Drawbacks](#drawbacks)
* [Alternatives](#alternatives)
* [References](#references)

---

## Summary

This PR introduces `LoadBalancingRouter`, a router that distributes LLM requests across multiple endpoints based on estimated Time to First Token (TTFT). The goal is to improve user Quality of Experience by:

* Predicting TTFT per request using prompt length, endpoint load, and endpoint hardware characteristics.
* Levering Key-Value (KV)Cache hits to minimize redundant computation.

---

## Motivation

The motivation behind this work is to improve the responsiveness and perceived latency of LLM responses, thereby enhancing the overall user experience. By maximizing efficiency through the reuse of previously cached tokens, the system can reduce redundant computation and accelerate response times. Routing decisions are guided by the goal of optimizing Time To First Token (TTFT), a critical user-facing Quality of Experience (QoE) metric that directly impacts how quickly users perceive the system to be reacting to their inputs.

---

## Goals

* Route requests to the endpoint with the lowest estimated TTFT.
* Integrate KVCache hits to reduce effective prompt length and TTFT.
* Monitor and adapt to real-time load across endpoints.
* Maintain accurate, up-to-date statistics for each endpoint including current load and request completion times.

---

## Non-Goals

* End-to-end latency optimization: This router focuses on improving TTFT, not full response latency or total token generation time.
* Model-specific optimizations: The logic does not include fine-tuning or customization for specific LLM architectures beyond general hardware and load awareness.
* Multi-request batching: This implementation assumes one request per routing decision and does not batch multiple requests together for simultaneous execution.

---

## Proposal

### Proposed Changes

* Introduce `estimate_ttft()` function that uses a hardware-aware formula based on endpoints' model parameters, FLOPS, memory bandwidth rate.
* Infer said endpoint-specific hardware capabilities based on endpoint names.
* Add tokenization and KVCache lookup logic to reduce effective prompt length.
* Integrate per-endpoint load tracking and update logic.
* Establish cache-aware routing by incorporating KV reuse in endpoint selection (`instance_id.best_instance_id`).

### Implementation Details/Notes/Constraints

![Model Workflow](imgs/load_balancing_workflow.png)

#### Estimate TTFT (if no tokens are found in cache)

The TTFT is estimated based on model parameters, prompt length, hardware throughput, and current endpoint load:

* `compute = (2 * self.model_params * effective_prompt_len) / self.flops_rate`
* `memory = (2 * self.model_params) / self.hbm_rate`
* `scaled_ttft = (compute + memory) * (1 + load)` → Final TTFT estimate factoring in the current endpoint load.

#### `EndpointStats`

Each endpoint maintains lightweight runtime statistics to guide routing decisions:

* **Current number of in-flight requests** (`load`)
  → Reflects real-time congestion or availability.

* **Rolling average of request completion time**

  → Smooths recent durations to estimate responsiveness.

**Load counter updates:**

* `increment_load()` when a request is dispatched.
* `decrement_load()` when a request completes.

---

## Test Plans

* Unit test TTFT estimation with various prompt lengths and cache hit patterns.
* Simulate multiple endpoints with varying loads and validate routing behavior.
* Measure improvements in average TTFT and request latency across scenarios.
* Validate that fallback logic and cache-integration logic perform as expected under edge cases.

---

## Drawbacks

* Endpoint metrics are determined based on name, e.g, 8B is assumed to be 8 billion.
* Integration with the cache controller adds coupling and potential latency overhead.
* The additional tokenization and cache lookup step adds preprocessing time for short prompts.

---

## Alternatives

* Use a simple round-robin or weighted load balancer.
* Train an ML model to predict TTFT using past routing data.

---

## References

[Estimate VRAM Usage in LLM Inference](https://www.jinghong-chen.net/estimate-vram-usage-in-llm-inference/)
