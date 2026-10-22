# Learning log

## 2026-09-22 — production-stack: repo overview
- Misconception: thought the `operator` "keeps helm going".
- Reality: helm and operator are independent, alternative deployment methods — not chained. Helm = one-shot templated install, nothing runs after. Operator = continuously running Go controller that reconciles state.
- Fix: pick one deployment method per install, don't think of one as managing the other.

- Misconception: thought `docker/` folder = running pod storing dependencies.
- Reality: `docker/` just holds Dockerfiles — build-time recipes for container images (router, kvaware variant, sidecar variant). "Pod" is a separate k8s runtime concept.
- Fix: image build (docker/) vs runtime scheduling (k8s/pod) are different layers.

- Core model: `src/vllm_router` = discovery (service_discovery.py: who's alive) → routing (routing_logic.py: pick one, strategies like round robin/kv-aware/prefix-aware/session) → forward (services/). Tests in `src/tests/` map 1:1 to router strategy classes.

## 2026-09-22 — routing_logic.py: key normalization and consistent hashing
- Insight: `RoundRobinRouter` keys its counter dict by `sorted(tuple(urls))` — without sorting, the same endpoint set in a different list order looks like a "new" key, so the counter fragments and round-robin stops being fair. General pattern: normalize before using something as a cache/dict key.
- Insight: `SessionRouter` avoids that bug differently — not by sorting, but by keeping one persistent `HashRing` object mutated via add/remove (set diff), not re-derived from a key each call.
- Insight: `SessionRouter` uses consistent hashing (`HashRing`) instead of `hash(session_id) % len(endpoints)` because plain modulo remaps almost every session when the endpoint count changes (autoscaling). Since sessions exist to preserve KV-cache locality, mass remapping would defeat the router's whole purpose.

## 2026-09-23 — PR reading: #969 (forward /sleep query params) + candidate first PR
- Read PR #969 end to end: bug was that `route_sleep_wakeup_request` built the upstream `url` from path only, never read `request.query_params`, so `level`/`mode`/`tags` were silently dropped. Fix: forward all query params except router-only `id` via aiohttp's `params=`.
- Insight: PR explicitly scoped out registering `/collective_rpc` and `/reset_prefix_cache` as a "follow-up" to keep the pure bugfix mergeable fast, without bundling in open design questions (new endpoints, auth/rate-limit). Good scoping pattern to copy.
- Candidate first PR: checked — `/collective_rpc` and `/reset_prefix_cache` still aren't registered through the router (grep of src/ found nothing, no PR since). Real, unclaimed gap, in code area (`route_sleep_wakeup_request`) I already understand.
