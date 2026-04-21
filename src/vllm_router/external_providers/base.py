import abc
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, Optional

from vllm_router.external_providers.models import ExternalProviderConfig


@dataclass
class ExternalProviderResponse:
    """
    Standardized response format for external provider responses.

    This can be extended with additional fields as needed (e.g., status code, headers).
    """

    status_code: int
    headers: Dict[str, str] = field(default_factory=dict)
    body: Optional[Any] = None
    is_stream: bool = False
    stream_iterator: Optional[AsyncIterator[bytes]] = (
        None  # For streaming responses, an iterator over response chunks
    )


@dataclass
class ExternalProviderAdapter(abc.ABC):
    """
    Abstract base class for external provider adapters.

    Lifecycle:
    1. The adapter is initialized with an ExternalProviderConfig.
    2. `send_request` is called for each incoming request to an external model.
    3. `health_check` is called periodically to check the availability of the provider.
    4. `close` is called when the adapter is being shut down to clean up resources.
    """

    def __init__(self, config: ExternalProviderConfig):
        self.config = config

    @abc.abstractmethod
    async def send_request(
        self, endpoint: str, payload: dict, stream: bool = False
    ) -> ExternalProviderResponse:
        """
        Send a request to the external provider.

        Args:
            endpoint: The API endpoint to call (e.g., "/v1/chat/completions").
            payload: The request payload as a dictionary.
            stream: Whether to return a streaming response.

        Returns:
            The response from the provider as an ExternalProviderResponse.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def health_check(self) -> bool:
        """
        Check the health of the external provider.

        Returns:
            True if the provider is healthy and reachable,
            False otherwise.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def close(self) -> None:
        """
        Clean up any resources used by the adapter (e.g., close HTTP sessions).
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def fetch_available_model_ids(self) -> list[str]:
        """
        Fetch the list of model IDs actually available at the provider.

        This queries the provider's /v1/models endpoint (or equivalent) and
        returns the canonical IDs it reports. Used at startup to validate that
        the models in the config are actually offered by the provider.

        Returns:
            A list of model IDs the provider currently serves.
        """
        raise NotImplementedError

    def get_provider_name(self) -> str:
        """
        Get the name of the provider this adapter is for.

        Returns:
            The provider name as specified in the configuration.
        """
        return self.config.name
