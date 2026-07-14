## Table of Contents
- [Summary](#summary)
- [Motivation](#motivation)
- [Proposal](#proposal)
- [Drawbacks](#drawbacks)
- [Alternatives](#alternatives)
- [Implementation Timeline / Phases](#implementation-timeline--phases)
- [References](#references)
## Summary
This proposal adds a new routing algorithm `priority` to the vLLM Production Stack router. Each incoming request carries a priority value (from a request header or body field). The router uses this value to (1) steer higher-priority requests to the least-loaded serving engine for better time-to-first-token, and (2) forward the priority to vLLM so its native priority scheduler can preempt lower-priority work within an engine. Together this gives operators a way to guarantee preferential treatment for latency-sensitive or business-critical traffic when the cluster is under contention.
## Motivation
In multi-tenant or mixed-workload deployments, not all requests are equally important. Interactive chat sessions, paid tiers, or health-check probes may need to be served ahead of bulk/batch traffic. Today the production-stack router treats every request identically — round-robin, session, KV-aware, and prefix-aware routing all optimize for aggregate throughput or cache locality, with no notion of per-request importance.
- **Why is this feature needed?** Under load, latency-sensitive requests currently queue behind less important ones with no recourse. Operators have no lever to express “serve these first.”
- **What use cases does it address?** Tiered service levels (premium vs. free), prioritizing interactive over batch traffic, keeping health/readiness probes responsive under load, and de-prioritizing best-effort background jobs.
- **What current limitations does it alleviate?** The router cannot differentiate traffic by importance, and vLLM’s own priority scheduler is unreachable because no routing logic propagates a priority field to the engine.
### Goals
- Add `priority` as a new `--routing-logic` option.
- Extract a per-request priority from a configurable header or body field, with a configurable default.
- Route higher-priority requests to the least-loaded engine using existing engine load metrics.
- Forward the priority value into the request body so vLLM’s priority scheduler (when enabled) can preempt within an engine.
- Degrade gracefully to round-robin when engine load metrics are unavailable.
### Non-Goals
- Router-side request queuing or admission control (tracked separately in the request-queuing work).
- Preemption logic inside the engine (owned by vLLM’s scheduler).
- Fair-share or weighted-fair-queuing accounting across tenants.
- Guaranteeing strict ordering across engines (only best-effort steering plus in-engine scheduling).
## Proposal
### Proposed Changes
**Priority semantics.** We adopt vLLM’s convention so pass-through is lossless: `priority` is an integer where **lower means higher priority** (served earlier). The default is configurable (`--priority-default`, default `0`).
**Priority source.** Resolved in this order:
1. Request header named by `--priority-header` (default `x-request-priority`).
2. Request body field named by `--priority-field` (default `priority`).
3. `--priority-default`.
**Request flow:**
```text
┌──────────┐     priority=P     ┌───────────────────────────────┐
│  Client  │───────────────────▶│ Router (routing-logic=priority)│
└──────────┘                    └───────────────┬───────────────┘
                                                │ rank engines by load
                                                │ (in-flight requests)
                high priority ──────────────────┼────────▶ least-loaded engine
                normal priority ────────────────┼────────▶ round-robin (all engines)
                                                │
                                                │ inject “priority”: P into body
                                                ▼
                                    ┌────────────────┐
                                    │ vLLM engine    │ priority scheduler
                                    │ (preempts)     │ serves P first
                                    └────────────────┘
```
1. Client sends a request with a priority (header or body).
2. Router extracts the priority and ranks candidate engines by live, router-local load: `in_prefill_requests + in_decoding_requests` from the existing `RequestStatsMonitor` (`src/vllm_router/stats/request_stats.py`). These counters are updated synchronously on each request's lifecycle events (`on_new_request`, `on_request_response`, `on_request_complete`) rather than polled, so they carry no staleness window — unlike the scraped `EngineStats` (`num_running_requests`/`num_queuing_requests`), which is only as fresh as the last `--engine-stats-interval` scrape (default 30s) and is therefore not used for this per-request decision. This also matches how `SessionRouter`, `KvawareRouter`, and `PrefixAwareRouter` already fall back to `RequestStats`-based load (`_qps_routing`) rather than `EngineStats`.
3. The request is mapped to an engine according to the selection strategy below. Round-robin candidates always include every healthy engine — including the current least-loaded one — so capacity is never left idle if no high-priority traffic arrives. If `RequestStatsMonitor` has no data yet for an engine (cold start), it is treated as zero load.
4. Router injects `priority` into the forwarded body so vLLM's priority scheduler can preempt within the engine. If the engine was not started with `--scheduling-policy priority`, vLLM ignores the field with no adverse effect; since the router cannot introspect an engine's scheduling policy today, it logs a one-time startup warning reminding operators to verify their engines are configured for priority scheduling whenever `routing-logic=priority` is enabled.
5. Response streams back normally.
**Engine selection strategy.** Two strategies were considered for mapping a priority value onto the load-ranked engine list:
- **Option A — binary threshold (proposed default).** Requests more important than a configurable threshold (`priority < --priority-threshold`, default equal to `--priority-default`) are routed to the least-loaded engine; all other requests round-robin across **all** engines, including the least-loaded one. Using a strict `<` (rather than `<=`) means requests carrying the default priority are *not* automatically classified as high-priority — only requests explicitly marked below the threshold are — so priority routing stays opt-in with zero extra configuration. Because round-robin always considers every engine, no engine is ever reserved and left idle waiting for high-priority traffic that may never arrive. Simple to reason about, deterministic, and easy to unit-test. Selected as the default.
- **Option B — proportional rank mapping.** The priority value is mapped onto the load-ranked engine list so that the most important requests get the least-loaded engine and progressively lower-priority requests get progressively more-loaded engines. More granular, but the mapping is fuzzier, harder to test deterministically, and sensitive to how sparse or clustered the priority values are.
Both are compatible with the same router interface; the strategy could be exposed later via a `--priority-selection={binary,proportional}` flag if Option B proves useful. This proposal implements Option A first.
### Implementation Details/Notes/Constraints
- **Architecture / Components:**
- `src/vllm_router/routers/routing_logic.py` — new `RoutingLogic.PRIORITY` enum value and `PriorityRouter(RoutingInterface)` class; registration in `initialize_routing_logic`, `get_routing_logic`, and `cleanup_routing_logic`.
- `src/vllm_router/parsers/parser.py` — new CLI arguments and `--routing-logic` choice.
- `src/vllm_router/app.py` and `src/vllm_router/dynamic_config.py` — thread new kwargs through router initialization and dynamic reconfiguration.
- `src/vllm_router/services/request_service/request.py` — route via `PriorityRouter` and inject the priority field into the forwarded body.
- `src/vllm_router/stats/request_stats.py` — reuse `RequestStatsMonitor`'s `in_prefill_requests`/`in_decoding_requests` counters as the load signal, consistent with how other routers already prefer `RequestStats` over scraped `EngineStats`.
- **Interface Changes:** New CLI arguments:
| Argument | Default | Description |
| -------- | ------- | ----------- |
| `--routing-logic=priority` | — | Enable priority routing |
| `--priority-header` | `x-request-priority` | Header carrying the request priority |
| `--priority-field` | `priority` | Body field carrying the request priority |
| `--priority-default` | `0` | Priority used when none is provided |
| `--priority-threshold` | value of `--priority-default` | Requests with `priority < threshold` are treated as high-priority and routed to the least-loaded engine; default-priority requests do not qualify unless the operator lowers the threshold or raises the default (Option A) |
No changes to the client-facing OpenAI API surface; priority is opt-in via a header or the existing `priority` body field that vLLM already understands.
- **Performance Considerations:** One integer extraction and an O(N) scan over the candidate engines per request (N = replicas for the model). Negligible versus network I/O. No extra round-trips.
- **Resource Constraints:** No GPU usage; trivial CPU/memory in the router.
### Test plans
- **Unit Tests** (`src/tests/test_priority_router.py`): priority extraction precedence (header &gt; body &gt; default); highest-priority request selects the least-loaded engine; a request at the default priority is *not* treated as high-priority (exclusive threshold boundary); round-robin candidates include the least-loaded engine when no high-priority traffic is present; round-robin fallback when `RequestStatsMonitor` has no data; empty endpoint list raises `ValueError`.
- **Integration/E2E Tests:** With a running router plus two mock backends of differing load, verify a high-priority request lands on the least-loaded backend and that the forwarded body contains the `priority` field.
- **Negative Tests:** Non-integer / malformed priority values fall back to the default; missing header and body field use the default; single-engine deployments behave like round-robin.
## Drawbacks
- **Added configuration surface** — operators must choose a priority source and educate clients to set it.
- **Best-effort across engines** — routing steering cannot guarantee ordering across separate engines; strict preemption depends on vLLM's priority scheduler being enabled (`--scheduling-policy priority`).
- **Potential starvation** — persistently high-priority traffic could starve low-priority requests; mitigated by documenting the risk (fair-share is a non-goal here).
## Alternatives
1. **Do nothing** — operators cannot differentiate traffic; latency-sensitive requests suffer under load.
2. **Priority queuing only in the router** — richer control but couples this work to the in-progress request-queuing feature and duplicates vLLM's scheduler; deferred as a non-goal.
3. **Pass-through only (no load-aware steering)** — simpler, but under load a high-priority request can still land on a saturated engine, wasting the scheduler's benefit. Combining steering + pass-through gives both cross-engine and in-engine prioritization.
This proposal is the best approach because it reuses the existing routing-logic framework and the load metrics the router already scrapes, adds no new dependencies or round-trips, and complements (rather than reimplements) vLLM's native priority scheduler.
## Implementation Timeline / Phases
- **Phase 1:** `PriorityRouter`, CLI arguments, load-aware selection, priority pass-through, unit tests.
- **Phase 2:** Documentation, example manifests, and an E2E test.
## References
- 2026 Roadmap — "Implement priority routing" (P2): <a href="https://github.com/vllm-project/production-stack/issues/855">https://github.com/vllm-project/production-stack/issues/855</a>
- vLLM priority scheduling (`--scheduling-policy priority`, request `priority` field): <a href="https://docs.vllm.ai/en/latest/serving/engine_args.html">https://docs.vllm.ai/en/latest/serving/engine_args.html</a>
