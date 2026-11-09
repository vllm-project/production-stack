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
Session affinity then operates within healthy endpoints that have capacity.
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
3. Exclude unhealthy, sleeping, or capacity-limited endpoints.
4. Select an endpoint from the remaining load window, using session affinity when available.
5. Repeat the same restriction if request forwarding needs another endpoint.

Return an authentication error when identity cannot be established.
Return an authorization error when policy denies the requested model or group.
Return `503` when the allowed endpoints are unavailable or have no capacity.
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
The exact group source, reload behavior, and identity contract need review before implementation.
Unresolved groups must produce a clear configuration error or an unavailable pool.
They must not expand access.

#### Load and session behavior

Use request counters for current router-local load and engine metrics for optional capacity limits.
These signals have different lifetimes: scraped engine metrics can be stale.
Validate optional capacity metrics for freshness, finite values, and valid ranges.
If a configured hard check cannot be evaluated, exclude that endpoint.
Operators can leave that check disabled where the required metric is unavailable.

Stable hashing over tenant, session, and endpoint identity is one candidate for affinity.
First form a load window within the permitted, available endpoints.
Then apply affinity within that window.
This trades some affinity for overload avoidance and can move a session as load changes.
It does not guarantee cache reuse or prevent concurrent requests from consuming the last free capacity.

#### Boundaries and observability

Strip any internal gateway assertion before forwarding it to engines.
Do not log raw identity assertions or signing material.
If signed gateway metadata is selected, require bounded validity and define key rotation before implementation.
Such metadata remains replayable during its validity window unless a separate replay control is added.

Initially reject combinations with cross-tenant semantic caching or unfiltered external-provider paths.
Later support would need equivalent policy checks.
Use low-cardinality decision labels such as `allowed`, `unauthorized`, and `no_capacity`.
Do not add tenant IDs, sessions, or endpoint URLs as metric labels.

#### Performance and resources

Filtering requires a scan of the candidate endpoints for the requested model.
No GPU work or extra remote policy lookup is proposed in the request path.
CPU cost, session movement, and request latency still require measurement.
No production performance result is claimed.

### Test plans

- Unit tests: permitted-group filtering, model compatibility, stable selection, and load-window boundaries.
- Negative tests: unknown identity, invalid assertions, expired metadata, missing metrics, and empty allowed pools.
- Retry tests: failed endpoints and explicit endpoint requests cannot bypass pool restrictions.
- Integration tests: one router and two mock backend groups; confirm isolation on success and failure paths.
- Configuration tests: disabled policy preserves existing behavior; invalid configuration fails predictably.
- Helm tests: render policy mounts and existing Secret references without embedding credentials in values.
- Benchmarks before rollout: policy overhead, session movement, and tail latency under mixed interactive and batch load.

A public [prototype][prototype] explores a signed-gateway variant and bounded endpoint selection.
Its contract tests and Helm checks are useful design inputs.
They do not establish production isolation, performance, or upstream compatibility.
Any accepted implementation would be submitted separately against the agreed interfaces.

## Drawbacks

- Trusted identity and endpoint-group configuration add an operational responsibility.
- Stale or unavailable capacity metrics can reduce available capacity under a strict policy.
- Restricting retries to one pool can reject work while another pool has spare capacity.
- Load-window changes can move sessions and reduce cache locality.
- Router-local observations do not provide strict admission control across router replicas.

## Alternatives

1. Separate router and engine deployments per tenant. This offers a simpler boundary but adds operational cost.
2. Enforce pool routing in an external gateway. This can work, but retries inside this router still need an equivalent boundary.
3. Use authentication or session affinity alone. These do not define a tenant's permitted backend set.
4. Compose a shared endpoint filter with several routing policies. This may be preferable to a new routing enum.

The fourth option is an open design question.
Maintainer feedback should determine whether the filter belongs in the request path or a dedicated policy.

## Implementation Timeline / Phases

- Phase 1: agree on identity, endpoint groups, error behavior, and the shared-filter interface.
- Phase 2: implement bounded selection and retry checks with unit and mock-backend tests.
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
