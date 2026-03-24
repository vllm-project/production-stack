from typing import AsyncIterator

import aiohttp

from vllm_router.external_providers.base import (
    ExternalProviderAdapter,
    ExternalProviderResponse,
)
from vllm_router.external_providers.models import ExternalProviderConfig
from vllm_router.log import init_logger

logger = init_logger(__name__)


class OpenAIProvider(ExternalProviderAdapter):
    """
    Provider for OpenAI's API and any other provider that follows a similar API structure.

    Request flow:
    1. Receive OpenAI formatted request body from user.
    2. Resolve model alias to canonical ID if necessary.
    3. Inject Authorization header with Bearer token from config.
    4. Forward request to OpenAI API endpoint.
    5. Return response as-is to caller, supporting both standard and streaming responses.
    """

    def __init__(self, config: ExternalProviderConfig):
        super().__init__(config)
        self.api_key = config.get_api_key(default_env_var="OPENAI_API_KEY")
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp ClientSession for making requests."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.config.timeout)
            )
        return self._session

    def _build_headers(self) -> dict:
        """Build the headers for the request, including Authorization."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        headers.update(
            self.config.custom_headers
        )  # Include any additional headers from config
        return headers

    async def send_request(
        self, endpoint: str, payload: dict, stream: bool = False
    ) -> ExternalProviderResponse:
        session = await self._get_session()
        headers = self._build_headers()

        # Resolve model alias to canonical ID if necessary
        requested_model = payload.get("model", "")
        canonical_id = self.config.resolve_model_id(requested_model)
        if canonical_id and canonical_id != requested_model:
            logger.debug(
                f"Resolving model alias '{requested_model}' -> canonical ID '{canonical_id}'"
            )
            payload = {**payload, "model": canonical_id}

        url = self.config.api_base.rstrip("/") + endpoint
        logger.info(
            f"OpenAIProvider: sending request to ({url}) (model: {payload.get('model')})"
        )

        attempt = 0
        last_error = None
        while attempt <= self.config.max_retries:
            try:
                if stream:
                    return await self._send_streaming_request(
                        session, url, headers, payload
                    )
                else:
                    return await self._send_standard_request(
                        session, url, headers, payload
                    )
            except aiohttp.ClientError as e:
                last_error = e
                logger.debug(f"Request attempt {attempt} failed with error: {e}")
                attempt += 1
                if attempt <= self.config.max_retries:
                    logger.info(
                        f"Retrying request (attempt {attempt}/{self.config.max_retries}) after error: {e}"
                    )
                continue
        logger.error(
            f"OpenAIProvider: all {self.config.max_retries} retry attempts failed. Last error: {last_error}"
        )
        raise last_error

    async def _send_standard_request(
        self, session: aiohttp.ClientSession, url: str, headers: dict, payload: dict
    ) -> ExternalProviderResponse:
        async with session.post(url, json=payload, headers=headers) as response:
            response_data = await response.json()
            return ExternalProviderResponse(
                status_code=response.status,
                headers=dict(response.headers),
                body=response_data,
                is_stream=False,
            )

    async def _send_streaming_request(
        self, session: aiohttp.ClientSession, url: str, headers: dict, payload: dict
    ) -> ExternalProviderResponse:
        response = await session.post(url, json=payload, headers=headers)

        async def stream_chunks() -> AsyncIterator[bytes]:
            try:
                async for chunk in response.content.iter_any():
                    yield chunk
            finally:
                response.release()

        return ExternalProviderResponse(
            status_code=response.status,
            headers=dict(response.headers),
            body=None,
            is_stream=True,
            stream_iterator=stream_chunks(),
        )

    async def health_check(self) -> bool:
        try:
            session = await self._get_session()
            url = self.config.api_base.rstrip("/") + "/v1/models"
            headers = self._build_headers()
            async with session.get(url, headers=headers) as response:
                healthy = response.status == 200
                if not healthy:
                    logger.warning(
                        f"OpenAI Provider: Health check failed with status code: {response.status}"
                    )
                return healthy
        except aiohttp.ClientError as e:
            logger.warning(f"OpenAI Provider: Health check failed with error: {e}")
            return False

    async def fetch_available_model_ids(self) -> list[str]:
        """Query the provider's /v1/models endpoint and return available model IDs."""
        try:
            session = await self._get_session()
            url = self.config.api_base.rstrip("/") + "/v1/models"
            headers = self._build_headers()
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    logger.warning(
                        f"OpenAI Provider '{self.config.name}': "
                        f"failed to fetch models (status {response.status})"
                    )
                    return []
                data = await response.json()
                return [m["id"] for m in data.get("data", [])]
        except Exception as e:
            logger.warning(
                f"OpenAI Provider '{self.config.name}': "
                f"could not fetch available models: {e}"
            )
            return []

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info(f"OpenAI Provider: {self.config.name} session closed")
