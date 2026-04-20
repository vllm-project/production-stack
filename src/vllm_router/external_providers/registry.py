from typing import Dict, List, Optional, Tuple

from vllm_router.external_providers.base import ExternalProviderAdapter
from vllm_router.external_providers.models import ExternalProviderConfig
from vllm_router.log import init_logger

logger = init_logger(__name__)


def _build_adapter_registry() -> Dict[str, type[ExternalProviderAdapter]]:
    """
    Build a registry mapping provider names to their adapter classes.

    """

    registry: Dict[str, type[ExternalProviderAdapter]] = {}

    try:
        from vllm_router.external_providers.openai_provider import OpenAIProvider

        registry["openai"] = OpenAIProvider
    except ImportError as e:
        logger.debug(f"Failed to import OpenAIProvider: {e}")

    return registry


ADAPTER_REGISTRY: Dict[str, type[ExternalProviderAdapter]] = _build_adapter_registry()


class ExternalProviderManager:
    """
    Manages all registered external provider adapters.

    Responsibilities:
    1. Creates adapter instances from config and indexes model IDs.
    2. Lookup a model ID from a request, determines whether it's an external provider model
       and returns the corresponding adapter
    3. Provides all external model IDs for /v1/models endpoint.
    4. Probes providers for health status and model availability.
    5. Cleans up resources on shutdown.
    """

    def __init__(self):
        # provider_name -> adapter instance
        self._adapters: Dict[str, ExternalProviderAdapter] = {}
        # model_id -> (provider_name, adapter, canonical_model_id)
        self._model_index: Dict[str, Tuple[str, ExternalProviderAdapter, str]] = {}

    def register(self, config: ExternalProviderConfig):
        """
        Register an external provider from its configuration.

        Creates the corresponding adapter instance based on the provider name,
        and indexes all its model IDs and aliases.

        Args:
            config: The configuration for the external provider.
        """
        adapter_cls = ADAPTER_REGISTRY.get(config.type)  # Instead of config.name
        if adapter_cls is None:
            raise ValueError(
                f"No adapter found for provider type '{config.type}'. "
                f"Available types: {list(ADAPTER_REGISTRY.keys())}"
            )

        adapter = adapter_cls(config)
        self._adapters[config.name] = adapter

        for model in config.models:
            self._register_model_id(model.id, config.name, adapter, model.id)
            for alias in model.aliases:
                self._register_model_id(alias, config.name, adapter, model.id)

        logger.info(
            f"Registered provider '{config.name}'"
            f"(api_base={config.api_base}) with models: "
            f"{[model.id for model in config.models]}"
        )

    def _register_model_id(
        self,
        model_id: str,
        provider_name: str,
        adapter: ExternalProviderAdapter,
        canonical_id: str,
    ) -> None:
        """
        Register a model ID in the model index.
        """
        if model_id in self._model_index:
            existing_provider = self._model_index[model_id][0]
            if existing_provider != provider_name:
                raise ValueError(
                    f"Model ID '{model_id}' from provider '{provider_name}' "
                    f"conflicts with same model ID from provider '{existing_provider}'"
                )
        self._model_index[model_id] = (provider_name, adapter, canonical_id)

    def is_external_model(self, model_id: str) -> bool:
        """
        Check if a model ID belongs to an external provider.

        Args:
            model_id: The model ID to check.

        Returns:
            True if the model ID is registered to an external provider, False otherwise.
        """
        return model_id in self._model_index

    def lookup_adapter(self, model_id: str) -> Optional[ExternalProviderAdapter]:
        """
        Lookup the adapter for a given model ID.

        Args:
            model_id: The model ID to lookup.

        Returns:
            The corresponding ExternalProviderAdapter if found, None otherwise.
        """
        entry = self._model_index.get(model_id)
        if entry is None:
            return None
        return entry[1]

    def get_canonical_model_id(self, model_id: str) -> Optional[str]:
        """
        Get the canonical model ID for a given model ID (resolving aliases).

        Args:
            model_id: The model ID to resolve.

        Returns:
            The canonical model ID if found, None otherwise.
        """
        entry = self._model_index.get(model_id)
        if entry is None:
            return None
        return entry[2]

    def get_provider_name(self, model_id: str) -> Optional[str]:
        """
        Get the provider name for a given model ID.

        Args:
            model_id: The model ID to lookup.

        Returns:
            The provider name if found, None otherwise.
        """
        entry = self._model_index.get(model_id)
        if entry is None:
            return None
        return entry[0]

    def get_all_external_model_ids(self) -> list[str]:
        """
        Get a list of all model IDs registered to external providers.

        Returns:
            A list of all external model IDs.
        """
        return list(self._model_index.keys())

    def get_registered_providers(self) -> list[str]:
        """
        Get a list of all registered provider names.

        Returns:
            A list of registered provider names.
        """
        return list(self._adapters.keys())

    async def validate_models(self) -> None:
        """
        Validate registered models against each provider's live model list.

        Queries every provider's /v1/models endpoint and removes any model IDs
        (including aliases) from the index that the provider does not actually
        serve. This prevents misconfigured or unavailable models from being
        advertised or routed to.
        """
        for provider_name, adapter in self._adapters.items():
            available = set(await adapter.fetch_available_model_ids())
            if not available:
                logger.warning(
                    f"Provider '{provider_name}': could not fetch available models, "
                    "skipping validation (all configured models kept)"
                )
                continue

            to_remove = [
                model_id
                for model_id, (pname, _, canonical_id) in self._model_index.items()
                if pname == provider_name and canonical_id not in available
            ]
            for model_id in to_remove:
                del self._model_index[model_id]
                logger.warning(
                    f"Provider '{provider_name}': removing model '{model_id}' "
                    "— not found in provider's model list"
                )

            if to_remove:
                remaining = [
                    mid
                    for mid, (pname, _, _) in self._model_index.items()
                    if pname == provider_name
                ]
                logger.info(
                    f"Provider '{provider_name}': validated models, "
                    f"kept {remaining}, removed {to_remove}"
                )

    async def health_check(self) -> Dict[str, bool]:
        """
        Perform health checks for all registered providers.

        Returns:
            A dictionary mapping provider names to their health status (True for healthy, False for unhealthy).
        """
        health_status = {}
        for provider_name, adapter in self._adapters.items():
            try:
                is_healthy = await adapter.health_check()
                health_status[provider_name] = is_healthy
            except Exception as e:
                logger.error(f"Health check failed for provider '{provider_name}': {e}")
                health_status[provider_name] = False
        return health_status

    async def close(self) -> None:
        """
        Clean up resources for all registered providers.

        This should be called on application shutdown to ensure all provider sessions are properly closed.
        """
        for provider_name, adapter in self._adapters.items():
            try:
                await adapter.close()
                logger.info(f"Closed resources for provider '{provider_name}'")
            except Exception as e:
                logger.error(
                    f"Failed to close resources for provider '{provider_name}': {e}"
                )
        self._adapters.clear()
        self._model_index.clear()

    def __len__(self) -> int:
        """
        Get the number of registered providers.

        Returns:
            The number of registered providers.
        """
        return len(self._adapters)

    def __repr__(self) -> str:
        providers = list(self._adapters.keys())
        model_count = len(self._model_index)
        return (
            f"ExternalProviderManager(num_providers={len(providers)}, "
            f"num_models={model_count}, providers={providers})"
        )


def create_external_provider_manager(
    provider_configs: List[Dict],
) -> ExternalProviderManager:
    """
    Create an ExternalProviderManager from a list of provider configurations.

    Args:
        provider_configs: A list of dictionaries, each representing an external provider configuration.

    Returns:
        An instance of ExternalProviderManager with all providers registered.
    """
    manager = ExternalProviderManager()
    for config_dict in provider_configs:
        try:
            config = ExternalProviderConfig.from_dict(config_dict)
            manager.register(config)
        except Exception as e:
            logger.error(f"Failed to register provider from config {config_dict}: {e}")
            raise ValueError(f"Invalid provider configuration: {config_dict}") from e
    logger.info(f"External provider manager initialized: {manager}")
    return manager
