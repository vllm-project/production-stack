# Request Migration on Engine Failure

## Table of Contents

- [Summary](#summary)
- [Motivation](#motivation)
- [Proposal](#proposal)
- [Drawbacks](#drawbacks)
- [Alternatives](#alternatives)
- [Implementation Timeline / Phases](#implementation-timeline--phases)
- [Open Questions](#open-questions)
- [References](#references)

## Summary

This proposal makes the router resilient to vLLM engine failures. Today the router can only recover from a failure that happens *before* any response bytes are sent to the client. This proposal extends recovery in two steps: (1) retry on another engine for failures that are provably safe to retry (connection errors, backend `5xx` before the first byte, and non-streaming requests), and (2) **mid-stream migration**, where a streaming request whose engine dies after some tokens have already been delivered is transparently continued on a healthy engine, with no duplicated or lost tokens visible to the client.

This addresses the roadmap item "(P0) Request migration when the vLLM instance fails" in [#855](https://github.com/vllm-project/production-stack/issues/855).

## Motivation

Engine pods fail in normal operation: OOM, GPU/Xid errors, node preemption (spot), rolling upgrades, and autoscaler scale-in. Long generations (reasoning models, agents, long-form output) make the exposure window large: a request that has streamed for 60 seconds and then loses its engine is wasted work for the user and for the cluster.

### Current behavior

All references are to `src/vllm_router/services/request_service/request.py`.

- `route_general_request` has a failover loop (`max_instance_failover_reroute_attempts`, around line 621). It retries on another engine only if `process_request` raises **before it yields the response headers** (`await anext(stream_generator)`).
- Once headers are yielded and the body is streaming, an engine failure surfaces as an exception inside `traced_stream` and the client's stream is cut. No recovery is attempted.
- A backend `5xx` is not an exception. `process_request` yields the status code and the body to the client, so an engine that returns `500/503` (for example one that is crash-looping or shutting down) is not retried.
- `process_request` uses `aiohttp.ClientTimeout(total=None)`, so a hung engine (stalled, not closed) is never detected. The client waits indefinitely.
- Response bytes are forwarded as they arrive from `iter_any()`, with no awareness of SSE frame boundaries. The router cannot know which tokens were actually delivered.

### Goals

- A request that is safe to retry is retried on another healthy engine on `5xx`, connection failure, or stall before the first byte.
- A streaming request that loses its engine mid-generation continues on another engine, and the client receives one coherent stream: no duplicated tokens, no gap, one `[DONE]`.
- Migration is opt-in, bounded (maximum migrations per request), and observable (metrics, logs, trace attributes).
- Requests that cannot be migrated correctly are *not* silently corrupted. They fail the same way they do today, and a metric records why.
- Detect hung engines with a configurable inter-chunk stall timeout.

### Non-Goals

- Live KV-cache transfer from the failed engine. A crashed engine's KV cache is gone, and this proposal does not depend on engine-side changes.
- Deterministic reproduction of the output a failed engine *would* have produced. Migrated generation is a valid continuation, not an identical one (see [Semantics](#semantics-of-a-migrated-continuation)).
- Persisting request state across router restarts, or sharing state across router replicas. Migration state is in-memory and per-request.
- Replacing the autoscaler or health checking in the Kubernetes layer.
- Migrating disaggregated-prefill flows in the first version.

## Proposal

### Proposed Changes

#### 1. Failure classification

Introduce a small classifier that maps a failure to `retryable-before-first-byte`, `migratable-mid-stream`, or `fatal`:

| Failure | Before first byte | After first byte |
|---|---|---|
| Connect error / reset / DNS | retry | n/a |
| Backend `502/503/504` | retry | n/a (status already sent) |
| Backend `500` | retry (configurable) | n/a |
| Backend `4xx` | fatal (client error, pass through) | n/a |
| Connection dropped / `ClientPayloadError` / `ServerDisconnectedError` | retry | migrate |
| Stall (no chunk for `stall-timeout`) | retry | migrate |
| Client disconnect | stop, no retry | stop, no migration |

The failed engine is added to a per-request exclusion set so that the retry or migration never lands on the same engine.

#### 2. Streaming frame awareness

When migration is enabled for a request, the router stops forwarding raw byte chunks and instead forwards **complete SSE frames** (`data: ...\n\n`). A small incremental SSE parser:

- buffers a partial trailing frame and forwards only whole frames, so a half-written frame is never sent to the client;
- extracts the generated content from each forwarded frame (`choices[].text` for `/v1/completions`, `choices[].delta.content` for `/v1/chat/completions`) and appends it to a bounded per-request buffer;
- remembers the stream `id`, `created`, and `model` of the first frame, so that migrated frames can be rewritten to present a single coherent stream.

The buffer holds at most `max_tokens` worth of text per active migratable stream.

#### 3. Mid-stream migration

When an engine fails after `N` frames have been forwarded, the router:

1. Selects a new engine using the active routing logic over the remaining healthy engines (the same selection path as the existing failover loop, so priority, session, prefix-aware and KV-aware routing all apply).
2. Builds a **continuation request** from the original request plus the text already delivered:
   - `/v1/completions`: `prompt = original_prompt + delivered_text`. `max_tokens` is reduced by the number of tokens already delivered.
   - `/v1/chat/completions`: append a partial `assistant` message containing the delivered text and set `continue_final_message: true` and `add_generation_prompt: false`, so that the engine continues the same assistant turn. `max_tokens` / `max_completion_tokens` is reduced.
3. Streams the new engine's response through the same frame-aware pipeline, with these rewrites:
   - drop the initial role-only chunk of a chat stream (the client has already seen it);
   - rewrite `id` / `created` / `model` to the values from the first segment;
   - suppress intermediate `[DONE]` and the final usage chunk of a segment unless it is the last segment;
   - emit one merged usage chunk (when `stream_options.include_usage` is set) whose `completion_tokens` is the sum over segments.
4. Repeats on further failures up to `--max-migrations-per-request`. When the budget or the healthy engines are exhausted, the stream is terminated with an SSE `error` frame and then closed, which is cleaner than a silent cut.

#### Semantics of a migrated continuation

Autoregressive sampling is a sequence of conditional draws, so a continuation conditioned on the delivered prefix is a statistically valid sample from the same model. It is not byte-identical to what the failed engine would have produced. Consequently:

- **Seeded requests** (`seed` set) cannot be reproduced after migration. Phase 1 treats them as non-migratable (retry-before-first-byte only), unless the operator opts in.
- **Tokenization boundaries:** re-tokenizing `prompt + delivered_text` can differ from the original token sequence at the join point. This changes the continuation only at the boundary and is acceptable in Phase 1. Phase 2 removes it by resuming from token ids (see below).

#### Eligibility (Phase 1)

A request is migratable mid-stream only if all of the following hold. Anything else keeps today's failure behavior and increments a `not_migratable{reason}` metric:

- `stream: true`, on `/v1/completions` or `/v1/chat/completions`
- `n == 1`, no `best_of`
- no `seed`
- no structured / guided output (`response_format`, `guided_*`): the grammar state would restart at the beginning of the continuation
- no tool / function calls (partial tool-call JSON cannot be safely resumed)
- no `echo`, no `prompt_logprobs`

Non-streaming requests are never migrated mid-flight (nothing has been sent to the client), but they **are** retried in full on another engine on failure, which is always safe.

### Implementation Details/Notes/Constraints

- **Architecture / Components:**
  - `src/vllm_router/services/request_service/request.py`: failure classification in `route_general_request`, and the migration loop around `process_request`.
  - new `src/vllm_router/services/request_service/migration.py`: SSE frame parser, continuation-request builder, stream rewriter, eligibility check.
  - `src/vllm_router/stats/` and service discovery: passive health ejection. An engine that fails N times in a window is temporarily excluded from routing without waiting for the next health probe.
  - `src/vllm_router/parsers/parser.py`: new flags. `src/vllm_router/app.py`: wiring.
- **Interface Changes** (all off by default; existing behavior is unchanged when disabled):
  - `--enable-request-migration`
  - `--max-migrations-per-request` (default `1`)
  - `--migration-stall-timeout-seconds` (inter-chunk stall detection; default disabled)
  - `--retry-on-backend-5xx` (retry `500/502/503/504` before the first byte)
  - New response header `X-Request-Migrations: <n>` (useful for debugging; also logged).
- **Metrics:**
  - `vllm_router:request_migrations_total{reason,outcome}`
  - `vllm_router:request_retries_total{reason}`
  - `vllm_router:migration_not_eligible_total{reason}`
  - `vllm_router:migration_gap_seconds` (time between the last token from the failed engine and the first token from the new one)
  - `vllm_router:migrated_tokens_total` (tokens re-prefilled on the new engine)
- **Performance Considerations:**
  - Disabled: no overhead.
  - Enabled: SSE frame parsing on the streaming path adds CPU per chunk and forwards at frame granularity instead of arbitrary chunk boundaries (negligible latency change for token-sized frames). This will be benchmarked against the current passthrough path.
  - A migration costs one extra prefill of `prompt + delivered_tokens` on the new engine. With prefix-aware or KV-aware routing, the router can prefer an engine that already holds the shared prefix, which reduces this cost.
- **Resource Constraints:** a bounded text buffer per migratable stream (up to `max_tokens` characters). No GPU impact on the router.
- **Interaction with other features:**
  - *Priority routing* ([#996](https://github.com/vllm-project/production-stack/pull/996)): the continuation request keeps the original priority.
  - *Router-side queuing* ([#876](https://github.com/vllm-project/production-stack/pull/876)): a migrated request should re-enter admission with a priority boost so that it does not wait behind newer arrivals. This is a follow-up once queuing lands.

### Test plans

- **Unit Tests:**
  - SSE frame parser: split frames at arbitrary byte boundaries, multi-frame chunks, `[DONE]`, malformed frames.
  - Continuation builder for completions and chat (prompt concatenation, `continue_final_message`, `max_tokens` arithmetic).
  - Stream rewriter: id/created stability, dropped role chunk, merged usage.
  - Failure classifier and eligibility rules (every ineligible case).
- **Integration/E2E Tests:**
  - A fake backend that dies (connection reset / `kill`) after `k` frames: assert the client sees one coherent stream with exactly the expected total token count and a single `[DONE]`.
  - A fake backend that stalls: assert detection after the stall timeout and migration.
  - Backend returns `503` before the first byte: assert retry on another engine.
  - Migration budget exhausted: assert the SSE error frame and clean close.
  - Run against a real vLLM engine in at least one test to validate `continue_final_message` behavior on the pinned vLLM version.
- **Negative Tests:** invalid flag values, migration enabled with unsupported routing logic (disaggregated prefill), a single healthy engine, client disconnect during migration (no leaked tasks or stats entries), and `request_stats` consistency (no double-counted or never-completed requests after a migration).

## Drawbacks

- Complexity in the hottest path of the router (streaming proxy), including a new parser that must be correct under arbitrary chunking.
- Migrated output is a valid continuation, not an identical one. Some users with strict reproducibility needs will want it disabled for their traffic (it is opt-in and excluded for seeded requests).
- Re-prefill cost on migration, which is highest for long prompts and long delivered outputs.
- Token accounting is approximate in Phase 1 (see Open Questions).
- Restricted eligibility means structured-output and tool-calling workloads, where agent traffic is concentrated, are not covered at first.

## Alternatives

- **Client-side retry.** Simple, but it forces every client to implement deduplication and resume, and clients do not know which tokens were delivered correctly. Rejected as the primary mechanism.
- **Restart the stream from scratch on another engine.** Easy, but the client would receive duplicated content. Only suitable for non-streaming requests, which this proposal already covers.
- **Live KV-cache migration (for example via LMCache or NIXL).** Preserves exact state and avoids re-prefill, but it requires the source engine to be alive. It helps planned drains (scale-in, rolling upgrades) but not crashes, and it needs engine-side support. Worth a later phase for the planned-drain case, using the same router-side orchestration.
- **Do nothing.** Every engine failure continues to cost users their in-flight long generations, and operators must over-provision or avoid spot capacity.

## Implementation Timeline / Phases

Delivered as small, independently reviewable PRs:

- **Phase 0 (this RFC):** agree on scope, eligibility, and flags.
- **Phase 1a: safe retries.** Failure classifier, `--retry-on-backend-5xx`, full retry of non-streaming requests, stall timeout for hung engines, passive ejection, metrics. No streaming changes.
- **Phase 1b: streaming migration.** SSE frame parser, continuation builder for completions and chat, rewriter, `--enable-request-migration`, E2E tests with a fault-injecting fake backend.
- **Phase 2: exact resume.** Resume from token ids instead of text (removes the tokenization-boundary drift and gives exact usage accounting) once the engine API for returning and accepting token ids is confirmed on the supported vLLM versions. Prefix-aware target selection to cut re-prefill cost.
- **Phase 3: integration.** Re-admission with priority boost after queuing lands, planned-drain migration using KV transfer, and extended eligibility (structured output, tool calls).

## Open Questions

1. **Scope of "instance fails".** Does the roadmap item also cover planned drains (scale-in, rolling updates) or only unplanned failures? This RFC treats unplanned failures as the target and leaves planned drains to Phase 3.
2. **Token ids.** Does the supported vLLM version expose generated token ids in streaming responses (for example via `return_token_ids`) and accept token-id prompts on both endpoints? This determines whether Phase 2 can be done without engine changes.
3. **Usage accounting.** In Phase 1, `prompt_tokens` and `completion_tokens` in a merged usage chunk are derived from segment usage and delivered frame counts. Is approximate accounting acceptable until Phase 2?
4. **Default for `500`.** Should a backend `500` before the first byte be retried by default, given that some `500`s are request-specific (for example a bad request that crashes the handler) and could be retried onto every engine?
5. **Overlap.** Is anyone already working on retry or failover improvements that this should be coordinated with?

## References

- [Roadmap #855: (P0) Request migration when the vLLM instance fails](https://github.com/vllm-project/production-stack/issues/855)
- [Priority routing #996](https://github.com/vllm-project/production-stack/pull/996)
- [Router-side request queuing RFC #876](https://github.com/vllm-project/production-stack/pull/876)
- Existing failover loop: `src/vllm_router/services/request_service/request.py` (`route_general_request`, `process_request`)
