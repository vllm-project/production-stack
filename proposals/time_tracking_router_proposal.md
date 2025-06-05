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
* [Implementation Timeline / Phases](#implementation-timeline--phases)

---

## Summary

This PR introduces `TimeTrackingRouter`, a routing strategy that selects the optimal endpoint for requests by scoring them based on mean completion time and variability. This approach improves quality of experience (QoE) in serving LLM or similar model endpoints by balancing speed and reliability.

---

## Motivation

Current routing approaches may overload endpoints or ignore latency variability, leading to inconsistent user experiences. This feature addresses the need for a smarter, performance-aware router that makes routing decisions based on endpoint statistics, reducing response time variability and improving overall system efficiency.

---

## Goals

* Track per-endpoint mean and standard deviation of completion times
* Use a configurable weighted scoring function to rank endpoints.

---

## Non-Goals

* Token-level latency tracking (TTFT, ITL) is not implemented in this PR.
* Does not handle user-level QoE or request priority at this stage.

---

## Proposal

### Proposed Changes

* Implement `TimeTrackingRouter` class with routing logic based on scoring function:
  `score = alpha * mean_completion + beta * current_load + gamma * std_completion`
* Add `EndpointStats` for stats tracking.
* Update routing and stats APIs to support dynamic updates and routing decisions.

### Implementation Details/Notes/Constraints

* Uses a fixed window of 100 most recent completion times per endpoint.
* Scores endpoints with missing stats as zero to favor exploration.
* Alpha, beta, gamma weights are configurable with sensible defaults.
* Minimal performance overhead expected; only simple arithmetic and in-memory stats tracking.

### Test Plans

* Unit tests covering stats calculations, scoring, and endpoint selection logic.
* Integration/E2E tests verifying correct routing behavior under varying load and latency scenarios.
* Negative tests verifying fallback behavior when data is incomplete or missing.

---

## Drawbacks

* Adds complexity to routing logic and state management per endpoint.
* Requires maintaining additional metrics which might increase memory usage slightly.
* Fixed window size may not adapt well to all workloads — future work needed for adaptive windowing.
* Load ignored, can cause overload and inconsistent experience

---

## Alternatives

* Use simple round-robin or random routing — simpler but less QoE-optimized.
* Implement full token-level latency aware routing — deferred for future enhancement due to complexity.

---

## Implementation Timeline / Phases

* **Phase 1 (This PR):** Core router implementation and unit tests.
* **Phase 2:** Integration testing and performance tuning.
* **Phase 3:** Future enhancements like user-level priority support, checking KV cache, balancing load.

---
