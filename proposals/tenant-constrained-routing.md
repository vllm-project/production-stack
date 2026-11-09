# Tenant-Constrained Routing With Session Affinity

## Table of Contents

- [Summary](#summary)
- [Motivation](#motivation)
- [Proposal](#proposal)
- [Drawbacks](#drawbacks)
- [Alternatives](#alternatives)
- [Implementation Timeline / Phases](#implementation-timeline--phases)
- [References](#references)

## Summary

This proposal adds an opt-in routing policy for shared inference clusters.
An operator assigns each tenant a set of permitted backend groups.
The router filters endpoints by that policy before it selects an engine.
The router preserves session affinity while the preferred endpoint remains eligible.
Retry and direct-endpoint paths must enforce the same group restriction.
This PR requests design feedback; it changes no runtime code.

## Motivation

Teams can share a logical model name while using different engine groups.
For example, interactive and batch workloads can require separate capacity pools.
An overloaded allowed pool must not cause a request to use another team's pool.
An affinity key alone does not express that restriction.

The proposed policy complements authentication and priority routing.
Authentication establishes who sent a request.
The pool policy limits which endpoints that identity may use.
Priority can still affect selection within the permitted endpoints.

### Goals

- Restrict each request to the tenant's permitted, model-compatible endpoints.
- Apply the restriction to initial selection, explicit endpoint requests, and retries.
- Retain stable session placement while allowed endpoints have capacity.
- Reject requests when no allowed endpoint is available.
- Keep existing behavior when the policy is disabled.
- Expose bounded decision metrics without tenant identifiers or credentials.

### Non-Goals

- GPU memory isolation, tenant quotas, billing, or weighted fair scheduling.
- Replacing the API-key authentication work in [PR #937][auth-pr].
- Guaranteed latency, throughput, or cache hit rates.
- Sharing semantic-cache entries across tenants.
- Changing the engine's token scheduler.

## Proposal

### Proposed Changes

Use the existing routing interface and factory to add an opt-in tenant policy.
The policy receives trusted tenant identity, an optional session key, and the requested model.
It resolves permitted endpoint groups before any load or affinity decision.

The identity source needs maintainer agreement.
A future authentication integration could supply it directly.
A trusted gateway could also attach authenticated metadata.
The router must not trust an unsigned tenant name supplied by an arbitrary client.
This proposal does not require a second API-key implementation.

The request path would perform these steps:

1. Resolve trusted identity and validate the policy configuration.
2. Filter the requested model's endpoints by permitted groups.
3. Evaluate endpoint health and the configured capacity checks.
4. Keep an eligible session's preferred endpoint; otherwise select an allowed fallback.
5. Repeat the same restriction if request forwarding needs another endpoint.

Return an authentication error when identity cannot be established.
Return an authorization error when policy denies the requested model or group.
Return `503` when no endpoint satisfies the configured health and capacity policy.
Do not fall back to an endpoint outside the permitted groups.

### Implementation Details/Notes/Constraints

#### Components

- `src/vllm_router/routers/routing_logic.py`: register the policy and reuse endpoint-selection interfaces.
- `src/vllm_router/services/request_service/request.py`: enforce policy on forwarding, retries, and explicit endpoint paths.
- Parser, startup, and dynamic configuration: validate the policy and pass configuration through existing initialization paths.
- Service discovery: resolve configured groups against current endpoint identities and the requested model.
- Helm: mount non-secret policy configuration separately from authentication credentials.

An initial static configuration could map tenant identities to named backend groups.
Each group would contain discovered endpoints for the requested model.
The exact group source and identity contract need review before implementation.
Unknown static group references must fail configuration validation.
A valid group with no eligible discovered endpoints is an unavailable pool at request time.
Neither condition may expand access.

#### Load and session behavior

Use request counters for current router-local load and engine metrics for optional capacity limits.
These signals have different lifetimes: scraped engine metrics can be stale.
Validate optional capacity metrics for freshness, finite values, and valid ranges.
Separate mandatory eligibility checks from optional telemetry behavior.
Tenant authorization, model compatibility, endpoint readiness, and configured hard limits remain mandatory.
Telemetry degradation must never widen the permitted endpoint set or disable these checks.

For each optional engine-metric check, configure an explicit mode:

- **Strict:** exclude an endpoint when the required metric is unknown, stale, non-finite, or invalid.
  If no endpoint remains eligible, return `503`.
  Do not switch this mode to advisory automatically during an outage.
- **Advisory:** tolerate a missing engine-metric observation within the permitted, ready endpoints.
  Reuse a valid last observation only within its configured maximum age.
  After that age, mark the metric unknown and use router-local request counters as a best-effort load signal.
  Keep an otherwise eligible affinity endpoint while independent hard checks remain satisfied.
  A valid observation above an active overload threshold still makes that endpoint ineligible.

Propose advisory mode as the default for optional engine telemetry; operators must select strict mode for hard capacity requirements.
Never replace an unknown observation with zero or claim that router-local counts prove engine-wide spare capacity.
Expose the degraded state through bounded metrics and rate-limited warnings.
This choice trades stronger capacity enforcement for availability and needs maintainer review.

Compute a stable preference order over authorized, model-compatible endpoint membership for each tenant, model, and session.
Rendezvous hashing is one candidate; the exact algorithm remains a design choice.
Determine the primary independently of transient request counts and health samples.
Keep that primary while it is ready and satisfies the configured checks.
A slightly less-loaded peer alone must not move the session.

If the primary fails health checks or crosses a configured overload threshold, select another eligible endpoint in the same permitted set.
Use separate overload and recovery thresholds, plus a configured recovery interval, to reduce repeated switching.
Validate the recovery threshold below the overload threshold and require a non-negative recovery interval at startup.
An overloaded primary becomes eligible again only after the recovery condition is satisfied.
Hysteresis must never override a failed hard check.
Bound recovery state per endpoint and treat it as router-local state.
Requests without a session key can use the existing load selector after the same eligibility filtering.

Affinity can still change after endpoint membership changes, failures, or overload.
It does not guarantee cache reuse or prevent concurrent requests from consuming the last free capacity.

#### Boundaries and observability

Strip any internal gateway assertion before forwarding it to engines.
Do not log raw identity assertions or signing material.
If signed gateway metadata is selected, require bounded validity and define key rotation before implementation.
Such metadata remains replayable during its validity window unless a separate replay control is added.

Reject unsupported combinations during startup validation, before the router accepts inference traffic.
Initially this includes tenant routing with an unpartitioned cross-tenant semantic cache or an unfiltered external-provider path.
An invalid configuration must fail startup with an actionable configuration error.
Later support would need equivalent policy checks.

If dynamic reload is supported, validate the complete candidate configuration before applying it atomically.
Reject an invalid reload and retain the last valid configuration; never partially apply it or silently disable tenant checks.
Request-time guards still enforce pool restrictions for request-supplied endpoint overrides and retries.
Startup validation covers static combinations; these guards cover request-specific choices.
Use low-cardinality decision labels such as `allowed`, `unauthorized`, and `unavailable`.
Do not add tenant IDs, sessions, or endpoint URLs as metric labels.

#### Performance and resources

Filtering and stable endpoint selection add CPU work over the requested model's candidate endpoints.
No GPU work or extra remote policy lookup is proposed in the request path.
CPU cost, session movement, and request latency still require measurement.
No production performance result is claimed.

### Test plans

- Unit tests: permitted-group filtering, model compatibility, and stable primary selection despite small load changes.
- Capacity tests: transient scrape failure, bounded last-observation age, advisory fallback, and strict-mode rejection with unknown metrics.
- Affinity tests: overload failover, recovery thresholds, recovery interval, endpoint membership changes, and requests without a session key.
- Negative tests: unknown identity, invalid assertions, expired metadata, invalid metric values, and empty allowed pools.
- Retry tests: failed endpoints and explicit endpoint requests cannot bypass pool restrictions.
- Integration tests: one router and two mock backend groups; confirm isolation on success and failure paths.
- Configuration tests: disabled policy preserves existing behavior; unsupported combinations fail before inference traffic is accepted.
- Reload tests, if supported: invalid candidates preserve the last valid configuration; successful reloads apply atomically.
- Helm tests: render policy mounts and existing Secret references without embedding credentials in values.
- Benchmarks before rollout: policy overhead, session movement, and tail latency under mixed interactive and batch load.

A public [prototype][prototype] explores a signed-gateway variant and bounded endpoint selection.
Its contract tests and Helm checks are useful design inputs.
Its load-window selection and strict missing-metric behavior differ from the design proposed here.
The revised advisory mode, affinity-first selection, and reload validation are proposed work, not implemented prototype features.
They do not establish production isolation, performance, or upstream compatibility.
Any accepted implementation would be submitted separately against the agreed interfaces.

## Drawbacks

- Trusted identity and endpoint-group configuration add an operational responsibility.
- Stale or unavailable capacity metrics can reduce available capacity under a strict policy.
- Advisory telemetry can admit work to a busy engine when engine-wide capacity is unknown.
- Restricting retries to one pool can reject work while another pool has spare capacity.
- Affinity-first selection can retain uneven load until a configured overload threshold triggers failover.
- Failure, membership changes, and recovery can still move sessions and reduce cache locality.
- Hysteresis adds configuration and router-local endpoint state that must remain bounded.
- Router-local observations do not provide strict admission control across router replicas.

## Alternatives

1. Separate router and engine deployments per tenant. This offers a simpler boundary but adds operational cost.
2. Enforce pool routing in an external gateway. This can work, but retries inside this router still need an equivalent boundary.
3. Use authentication or session affinity alone. These do not define a tenant's permitted backend set.
4. Compose a shared endpoint filter with several routing policies. This may be preferable to a new routing enum.

The fourth option is an open design question.
Maintainer feedback should determine whether the filter belongs in the request path or a dedicated policy.

## Implementation Timeline / Phases

- Phase 1: agree on identity, endpoint groups, capacity modes, affinity recovery, and the shared-filter interface.
- Phase 2: implement the agreed selection, validation, and retry checks with unit and mock-backend tests.
- Phase 3: add deployment examples, configuration validation, and measured rollout guidance.

## References

- [Contribution process and proposal template][contributing]
- [Multi-API-key authentication PR #937][auth-pr]
- [Priority-routing proposal][priority]
- [Public routing prototype][prototype]

Prepared with AI assistance. The proposal was checked against the current router interfaces and related proposal.
It requests design review and does not claim upstream acceptance.

[contributing]: ../CONTRIBUTING.md
[auth-pr]: https://github.com/vllm-project/production-stack/pull/937
[priority]: priority-routing.md
[prototype]: https://github.com/hfeiuhog/servemesh-inference/tree/enterprise
