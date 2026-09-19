# Copyright 2024-2025 The vLLM Production Stack Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Retry policy for requests forwarded to a backend engine.

A forwarded request fails in one of two ways, which call for opposite responses:

* **Transport failure** (connection refused, timeout). The engine could not serve
  the request at all, so it is excluded and the request is rerouted to another
  engine immediately -- waiting would only add latency.
* **Retryable status** (408, 429, 500, 502, 503, 504). The engine is reachable
  but cannot take the request right now, so it stays eligible and the request is
  re-issued after a backoff.

Backoff is exponential with jitter::

    delay  = min(initial_backoff_ms * multiplier ** retry, max_backoff_ms)
    delay' = delay * (1 + U[-jitter_factor, +jitter_factor])

Without the jitter, routers that backed off from the same incident retry in
lockstep and re-create the overload they backed off from.

Retrying is opt-in; the default config allows a single attempt.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import AsyncIterator, List, Optional, Sequence

from fastapi import HTTPException

from vllm_router.log import init_logger

logger = init_logger(__name__)

RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


def is_retryable_status(status_code: int) -> bool:
    return status_code in RETRYABLE_STATUS_CODES


@dataclass(frozen=True)
class RetryConfig:
    """Validated retry parameters.

    ``max_attempts`` counts the initial request, so ``1`` disables retrying and
    ``5`` allows the initial attempt plus four retries.
    """

    max_attempts: int = 1
    initial_backoff_ms: int = 50
    max_backoff_ms: int = 30_000
    backoff_multiplier: float = 1.5
    jitter_factor: float = 0.2

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("Retry max attempts must be at least 1.")
        if self.initial_backoff_ms <= 0:
            raise ValueError("Retry initial backoff must be greater than 0.")
        if self.max_backoff_ms < self.initial_backoff_ms:
            raise ValueError(
                "Retry max backoff must be greater than or equal to initial backoff."
            )
        if self.backoff_multiplier < 1.0:
            raise ValueError("Retry backoff multiplier must be at least 1.0.")
        if not 0.0 <= self.jitter_factor <= 1.0:
            raise ValueError("Retry jitter factor must be between 0.0 and 1.0.")

    @property
    def enabled(self) -> bool:
        return self.max_attempts > 1

    def backoff_seconds(self, retry_index: int) -> float:
        """Jittered delay before retry ``retry_index`` (0-based)."""
        delay_ms = min(
            self.initial_backoff_ms * self.backoff_multiplier**retry_index,
            self.max_backoff_ms,
        )
        if self.jitter_factor:
            spread = random.uniform(-self.jitter_factor, self.jitter_factor)
            delay_ms = max(0.0, delay_ms * (1 + spread))
        return delay_ms / 1000.0

    @classmethod
    def from_args(cls, args) -> "RetryConfig":
        """Build a config from parsed CLI arguments.

        Without ``--enable-retries`` the other flags are ignored, so a shared
        config template carrying them cannot change behaviour or block startup.
        """
        if not getattr(args, "enable_retries", False):
            return cls()
        return cls(
            max_attempts=args.max_retries,
            initial_backoff_ms=args.initial_backoff_ms,
            max_backoff_ms=args.max_backoff_ms,
            backoff_multiplier=args.backoff_multiplier,
            jitter_factor=args.jitter_factor,
        )


RETRIES_DISABLED = RetryConfig()


class TransientBackendStatus(HTTPException):
    """A retryable backend status, as a raisable error.

    Subclasses ``HTTPException`` so that on the paths where the loop ends without
    a response, the client sees the backend's status rather than a router 500.
    """

    def __init__(self, server_url: str, status_code: int) -> None:
        super().__init__(
            status_code=status_code,
            detail=f"Backend {server_url} returned {status_code}",
        )
        self.server_url = server_url


class RetryState:
    """Per-request bookkeeping across attempts.

    Callers drive it with :meth:`attempts` and report each outcome.
    """

    def __init__(self, config: RetryConfig, request_id: str) -> None:
        self._config = config
        self._request_id = request_id
        self._excluded: set = set()
        self._attempt = 0
        self._retries_used = 0
        self._backoff_pending = False
        self.last_error: Optional[BaseException] = None

    @property
    def attempt_number(self) -> int:
        """1-based, for logging."""
        return self._attempt + 1

    @property
    def max_attempts(self) -> int:
        return self._config.max_attempts

    async def attempts(self, endpoints: Sequence) -> AsyncIterator[List]:
        """Yield the endpoints eligible for each attempt, sleeping for the
        backoff where one is due, until the budget is spent."""
        while self._attempt < self._config.max_attempts:
            if self._attempt == 0:
                candidates = list(endpoints)
            else:
                candidates = self._eligible(endpoints)
                if not candidates:
                    if not self._config.enabled:
                        return
                    # Every engine is excluded, but the failures may be
                    # transient, so retry the pool rather than give up.
                    self._excluded.clear()
                    candidates = list(endpoints)
                    self._backoff_pending = True
                if self._backoff_pending:
                    await self._backoff()
            yield candidates
            self._attempt += 1

    def should_retry_status(self, status_code: int) -> bool:
        return (
            self._config.enabled
            and is_retryable_status(status_code)
            and self._attempt + 1 < self._config.max_attempts
        )

    def record_transient_status(self, server_url: str, status_code: int) -> None:
        """Note a retryable status; the engine stays eligible."""
        self.last_error = TransientBackendStatus(server_url, status_code)
        self._backoff_pending = True
        logger.warning(
            f"Request {self._request_id} got retryable status {status_code} from "
            f"{server_url}, retrying (attempt {self.attempt_number}/"
            f"{self.max_attempts})"
        )

    def record_transport_failure(self, server_url: str, error: BaseException) -> None:
        """Note an unusable engine; it is excluded from further attempts."""
        self._excluded.add(server_url)
        self.last_error = error
        logger.warning(
            f"Request {self._request_id} failed on {server_url} "
            f"(attempt {self.attempt_number}/{self.max_attempts}): {error}"
        )

    def record_response(self) -> None:
        self.last_error = None

    def _eligible(self, endpoints: Sequence) -> List:
        return [ep for ep in endpoints if ep.url not in self._excluded]

    async def _backoff(self) -> None:
        delay = self._config.backoff_seconds(self._retries_used)
        self._retries_used += 1
        self._backoff_pending = False
        if delay <= 0:
            return
        logger.info(
            f"Request {self._request_id} waiting {delay:.3f}s before retry "
            f"{self._retries_used}/{self.max_attempts - 1}"
        )
        await asyncio.sleep(delay)
