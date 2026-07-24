# Router-Side Request Queuing for vLLM Router

## Table of Contents

- [Summary](#summary)
- [Motivation](#motivation)
- [Proposal](#proposal)
- [Drawbacks](#drawbacks)
- [Alternatives](#alternatives)
- [Implementation Timeline / Phases](#implementation-timeline--phases)
- [References](#references)

## Summary

This proposal adds router-side request queuing to the vLLM router as an admission-control layer in front of backend replicas. The goal is to smooth bursty traffic, keep backend `vllm:num_requests_waiting` shallow, and provide explicit overload behavior instead of immediately forwarding every request to already saturated replicas. The initial implementation is intentionally scoped to `roundrobin` routing only, with a design that can later be extended to `session`, `kvaware`, and `prefixaware` routing.

## Motivation

Today, the router immediately selects a backend and proxies the request. This works when capacity is available, but it provides no router-side backpressure when replicas are already overloaded. In practice, this means the system relies entirely on the backend's internal queue and offers no bounded waiting policy, no router-level fairness, and no clear `429` behavior for clients.

- **Why is this feature needed?** Bursty workloads can overwhelm backend replicas before autoscaling or normal scheduling has time to react. A router-side queue allows the stack to absorb short spikes and reject excess work cleanly when the queue budget is exhausted.
- **What current limitations does it alleviate?** The router currently has no admission control, no bounded wait time, and no explicit queue metrics for incoming requests.

### Goals

- Add bounded router-side queuing for inference requests before they are dispatched to a backend replica
- Use backend `num_requests_waiting` as the primary overload signal to decide when to queue or admit
- Preserve FIFO behavior at the model level for the initial implementation
- Provide explicit `429` responses for queue full, queue timeout, and pinned-endpoint overload conditions
- Make the implementation race-safe under bursty async workloads
- Add router-specific metrics for queue depth, wait time, admissions, rejections, and cancellations
- Keep the design extensible to future routing modes without requiring a redesign of the queue core

### Non-Goals

- Distributed or shared queueing across multiple router pods
- Persistent queue state across router restarts
- Priority scheduling or queue jumping
- Full support for `session`, `kvaware`, or `prefixaware` routing in the first implementation
- Queueing for `?id=` pinned-endpoint requests in the first implementation
- Changes to vLLM backend internals or backend scheduler behavior

## Proposal

### Proposed Changes

#### Overview

Add an in-memory `AdmissionController` to the router. Instead of directly dispatching every request to a backend, the router will:

1. Resolve the requested model and the set of eligible endpoints.
2. Consult the admission controller before dispatch.
3. Either:
   - admit the request immediately and return a lease for a specific endpoint,
   - enqueue the request in a bounded per-model FIFO queue, or
   - reject the request with `429` if queueing is not allowed or the queue budget is exhausted.

The queue does not wake all waiters when capacity changes. Instead, it grants concrete endpoint leases to specific queued requests and resumes only the requests that have actually been admitted. This avoids the thundering herd problem that would otherwise occur between wakeup and dispatch.

#### Admission Model

The controller maintains:

- a per-model FIFO queue of waiting requests
- a per-endpoint reservation count for requests that have been admitted by the router but have not yet been accepted by the backend

Admission is based on:

`backend_num_requests_waiting(endpoint) + local_reservations(endpoint) < waiting_threshold_per_endpoint`

This uses the backend's internal waiting queue depth as the primary overload signal and adds a router-local reservation count to cover scrape staleness and the dispatch gap between admission and backend acceptance.

#### Endpoint Leases

When the controller admits a request, it grants an `AdmissionLease` bound to a concrete endpoint URL. The request must dispatch to that endpoint directly and must not re-run routing after wakeup. This is required to make the reservation meaningful.

The lease lifecycle is:

1. Lease is created when the request is admitted.
2. Lease remains held while the request is in the router-to-backend dispatch gap.
3. Lease is released on first response chunk from the backend, because the backend has accepted the request into its processing pipeline.
4. Lease is also released if the request fails or is cancelled before the first response chunk.

#### Queue Policy in V1

- Queueing is enabled only for `roundrobin` routing.
- If router queueing is enabled with any other routing mode, router startup should fail with a validation error.
- Requests that target a specific endpoint via `?id=` are not queued in V1. They are admitted only if that endpoint is below the overload threshold; otherwise they are rejected immediately with `429`.
- If queueing is disabled, existing router behavior remains unchanged.

#### Routing Scope

Phase 1 does not attempt to solve affinity policy for `session`, `kvaware`, or `prefixaware`. Those modes have additional correctness and performance questions:

- should a session-pinned request wait only for its preferred backend or fall back after a timeout?
- should cache-locality-aware requests preserve locality even if another replica becomes available sooner?
- how should FIFO fairness interact with cache locality?

These policies should be addressed in follow-up phases after the base queueing machinery is proven in `roundrobin`.

### Implementation Details/Notes/Constraints

#### Architecture / Components

Expected implementation areas:

- `src/vllm_router/services/request_queue/`
  - new `AdmissionController`
  - queue entry and lease data types
- `src/vllm_router/services/request_service/request.py`
  - request admission before backend dispatch
  - lease release on first token / error / cancellation
- `src/vllm_router/routers/routing_logic.py`
  - `roundrobin` helper for selecting the next admissible endpoint
- `src/vllm_router/stats/engine_stats.py`
  - faster admission-oriented scrape interval when queueing is enabled
- `src/vllm_router/services/metrics_service/__init__.py`
  - router queue metrics
- `src/vllm_router/parsers/parser.py`
  - queue configuration flags
- `src/vllm_router/app.py`
  - admission controller initialization

#### Interface Changes

Proposed CLI flags:

- `--enable-router-queue`
- `--router-max-queued-requests`
- `--router-max-queue-wait-seconds`
- `--router-waiting-threshold-per-endpoint`
- `--router-admission-scrape-interval-seconds`

Proposed router metrics:

- `vllm_router:queued_requests`
- `vllm_router:queue_wait_seconds`
- `vllm_router:admissions_total`
- `vllm_router:rejections_total{reason}`
- `vllm_router:reservations`
- `vllm_router:queue_cancellations_total`

HTTP behavior changes:

- `429` when the router queue is full
- `429` when a request exceeds the configured router queue wait budget
- `429` when a `?id=` request targets an overloaded endpoint in V1

Existing `404` and `503` behavior for missing models and scaled-to-zero models remains unchanged.

#### Performance Considerations

- Queueing adds in-memory bookkeeping and lock contention inside the router, but should reduce backend overload and improve overall tail behavior during bursts.
- The controller must avoid `notify_all` patterns and avoid repeated re-routing after wakeup to prevent herd effects.
- Backend queue depth metrics are currently scraped on a relatively coarse interval. When router queueing is enabled, the router should scrape admission-relevant backend metrics more frequently, with a recommended default of 1 second.

#### Resource Constraints

- Queue state is stored in memory in each router process.
- Reservation tracking is lightweight, but queue memory usage grows with `router-max-queued-requests`.
- Queueing semantics are local to each router pod. In multi-router deployments, each router maintains an independent queue and there is no global fairness guarantee.

### Test plans

#### Unit Tests

- admission when capacity is available
- enqueue and dequeue ordering for per-model FIFO
- reservation creation and release lifecycle
- no thundering herd when multiple queued requests are waiting for one free slot
- cleanup on timeout, cancellation, and pre-first-token errors
- immediate `429` for `?id=` overload in V1

#### Integration/E2E Tests

- burst traffic against multiple fake backends to verify router queueing smooths dispatch
- first-token lease release behavior for streaming requests
- queue timeout behavior under sustained overload
- queue-full behavior with bounded queue size

#### Negative Tests

- enabling router queue with non-`roundrobin` routing logic
- zero or negative queue limits / timeouts
- missing or stale backend stats
- backend failure before first token

## Drawbacks

- Adds router complexity and new state management
- Queueing is local to a router pod, so fairness is not coordinated across multiple router replicas
- Admission decisions depend on scraped backend metrics and are therefore only as fresh as the configured scrape interval

## Alternatives

### Per-endpoint queues

This was considered, including the approach explored in the stale prototype PR. It was rejected for the initial design because endpoint selection at enqueue time becomes stale while requests wait, and because per-endpoint queues complicate fairness and rerouting semantics.

### Wake-all waiter model with re-check on wakeup

This was rejected because it is prone to thundering herd behavior between wakeup and actual dispatch, especially in async code where multiple coroutines can observe the same stale capacity before request stats are updated.

## Implementation Timeline / Phases

### Phase 1: Round-Robin Queueing

- Add in-memory admission controller
- Add per-model FIFO queue and per-endpoint reservations
- Release reservations on first response chunk or pre-first-token failure
- Add CLI flags and router queue metrics
- Support `roundrobin` routing only
- Reject queue enablement for other routing modes

### Phase 2: Session Routing Support

- Extend the queue core to support session-affinity-aware admission
- Define and document strict vs soft session stickiness
- Add tests for pinned-session fairness and fallback behavior

### Phase 3: KV-Aware and Prefix-Aware Support

- Define locality-aware queueing policy for LMCache-backed routing
- Extend routing interfaces as needed to express preferred endpoint ordering and fallback semantics
- Add tests for cache-locality behavior under queueing

## References

- [GitHub Issue #855: Router-side request queuing support](https://github.com/vllm-project/production-stack/issues/855)
- [GitHub PR #626: stale prototype for router-side queueing](https://github.com/vllm-project/production-stack/pull/626)
- [Proposal template](./TEMPLATE.md)
