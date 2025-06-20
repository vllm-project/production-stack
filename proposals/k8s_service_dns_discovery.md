# Use Kubernetes Service DNS for Engine Discovery

## Table of Contents

- [Summary](#summary)
- [Motivation](#motivation)
- [Proposal](#proposal)

## Summary

This proposal suggests updating the `K8sServiceDiscovery` class in `src/vllm_router/service_discovery.py` to utilize Kubernetes service internal DNS names for discovering vLLM engines, instead of relying on individual pod IP addresses. This change aims to improve the router's resilience by preventing traffic from being sent to terminated or unhealthy engine pods, which can occur when pod IPs change or pods are rescheduled.

## Motivation

The current implementation of `K8sServiceDiscovery` directly uses pod IP addresses. When a vLLM engine pod fails, is rescheduled, or its IP changes for any other reason, the router might continue to attempt sending requests to the old, now invalid, IP address. This leads to request failures and service disruptions until the service discovery mechanism updates its list of available engines.

- **Why is this feature needed?** To enhance the reliability and robustness of the vLLM routing layer in dynamic Kubernetes environments.
- **What use cases does it address?** Routing requests to vLLM engines deployed as Kubernetes services, especially in environments with frequent pod scaling or rescheduling.
- **What current limitations does it alleviate?** Reduces failures caused by the router attempting to connect to dead or non-existent engine pod IPs.

### Goals

- Modify `K8sServiceDiscovery` to discover and use Kubernetes service DNS names corresponding to vLLM engine deployments.
- Ensure that the routing logic can resolve these DNS names to appropriate, healthy pod IPs at the time of routing or through a periodic refresh.
- Update the engine statistics collection mechanism (`EngineStatsScraper`) to correctly aggregate stats from all pods backing a discovered service DNS name.

### Non-Goals

- This proposal does not aim to change the underlying mechanism of how vLLM engines themselves are deployed or managed within Kubernetes.
- It will not introduce a new service discovery method beyond Kubernetes services (e.g., Consul, Eureka).
- It will not alter the core routing algorithms, only the source of endpoint information.

## Proposal

### Proposed Changes

1. **Modify `K8sServiceDiscovery`:**
   - Instead of watching for individual pods and extracting their IPs, the discovery will watch for Kubernetes `Service` objects that match a specific label selector (identifying them as vLLM engine services).
   - The discovered `EndpointInfo` will store the service's internal DNS name (e.g., `my-vllm-service.namespace.svc.cluster.local`) instead of a direct pod IP.
   - The model(s) name associated with a service will be determined by scraping the `/v1/models` endpoint of the service DNS name.

2. **Adapt Request Routing:**
   - When a request needs to be routed, the router will use the service DNS name. Kubernetes' internal DNS will handle resolving this name to a healthy pod IP from the service's endpoints. This leverages Kubernetes' own load balancing and health checking for services.

3. **Update `EngineStatsScraper`:**
   - The `EngineStatsScraper` currently expects a direct URL (with an IP) for each engine. This will need to be adapted.
   - When a service DNS name is discovered, the scraper will need to:
     - Resolve the DNS name to its current set of backing pod IPs (e.g., by querying Kubernetes API for the `Endpoints` object associated with the service).
     - Scrape metrics from each of these pod IPs individually.
     - Aggregate these stats if necessary, or maintain them per-pod but associated with the overarching service. The `get_engine_stats` method might need to return a structure that reflects this (e.g., mapping a service DNS to a list of `EngineStats` from its pods, or an aggregated `EngineStats`).

### Implementation Details/Notes/Constraints

- **Architecture / Components:**
  - `src/vllm_router/service_discovery.py` (`K8sServiceDiscovery` class) will be significantly modified.
  - `src/vllm_router/stats/engine_stats.py` (`EngineStatsScraper` class) will require changes to how it fetches and potentially aggregates metrics.
  - The routing logic that consumes `EndpointInfo` might need slight adjustments if the format of the URL/identifier changes significantly (though ideally, using a DNS name as a URL should be transparent to `httpx`).
- **Interface Changes:**
  - The configuration for `K8sServiceDiscovery` might need to change to specify label selectors for `Service` objects instead of pod label selectors.
  - The structure of data returned by `EngineStatsScraper.get_engine_stats()` might change to accommodate multiple pods per service.
- **Performance Considerations:**: minimal impact expected.

- **Resource Constraints:** Minimal impact expected.

### Test plans

- **Unit Tests:**
  - Test the modified `K8sServiceDiscovery` logic with mock Kubernetes API responses to ensure correct service discovery and DNS name extraction.
  - Test the `EngineStatsScraper`\'s ability to resolve service DNS names to pod IPs and scrape metrics accordingly.
- **Integration/E2E Tests:**
  - Deploy vLLM engines as Kubernetes services and verify that the router correctly discovers them via their DNS names.
  - Simulate pod failures and rescheduling for a service and confirm that the router directs traffic only to healthy pods without significant interruption.
  - Verify that engine statistics are correctly collected and reported for services.
- **Negative Tests:**
  - Test behavior when a configured service label selector matches no services.
  - Test behavior when a discovered service has no healthy backing pods.
  - Test handling of DNS resolution failures.

## Drawbacks

- Increased complexity in `EngineStatsScraper` to handle DNS resolution and potential aggregation of stats from multiple pods per service.
- Reliance on Kubernetes internal DNS behaving as expected.
- Slightly more complex configuration if distinct label selectors for Services are introduced.
- Load balancing

## Alternatives

- **Improved IP-based Discovery with Stricter Health Checks:** Continue using pod IPs but implement more aggressive and reliable health checking before routing, and faster removal of dead IPs. This might still have a small window of failure.
- **Service Mesh Integration:** Utilize a service mesh (e.g., Istio, Linkerd) to handle routing and load balancing. This is a much larger architectural change and might be overkill if only this specific problem needs solving.
- **Do Nothing:** Continue with the current IP-based approach and accept the occasional failures due to stale pod IPs. This is not ideal for a production system requiring high availability.

This proposal is the best approach because it leverages built-in Kubernetes features (Services and DNS) for robustness, which is generally more reliable than custom IP management and health checking logic at the application level for this specific problem.

## Implementation Timeline / Phases

- **Phase 1:** Implement changes to `K8sServiceDiscovery` to discover services and use their DNS names.
- **Phase 2:** Adapt `EngineStatsScraper` to work with service DNS names and resolve them to pod IPs for metrics collection.
- **Phase 3:** Thorough testing (unit, integration, E2E) and documentation updates.

### Approximate dates

~2 weeks

## References

- (Link to relevant GitHub Issue if one is created)
- (Link to original Slack discussion thread or other internal discussions)
- Kubernetes Services: [https://kubernetes.io/docs/concepts/services-networking/service/](https://kubernetes.io/docs/concepts/services-networking/service/)
- Kubernetes DNS: [https://kubernetes.io/docs/concepts/services-networking/dns-pod-service/](https://kubernetes.io/docs/concepts/services-networking/dns-pod-service/)
