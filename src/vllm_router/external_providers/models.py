import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from vllm_router.log import init_logger

logger = init_logger(__name__)


@dataclass
class ExternalModelConfig:
    """A single external model configuration."""

    id: str
    type: str = "chat"
    aliases: list[str] = field(default_factory=list)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "ExternalModelConfig":
        """Create an ExternalModelConfig from a dictionary (from YAML)."""
        return ExternalModelConfig(
            id=data["id"],
            type=data.get("type", "chat"),
            aliases=data.get("aliases", []),
        )


@dataclass
class ExternalProviderConfig:
    """A single external provider configuration."""

    name: str
    type: str
    api_base: str
    models: list[ExternalModelConfig] = field(default_factory=list)
    api_key_env_var: Optional[str] = None

    timeout: float = 10.0
    max_retries: int = 3
    custom_headers: Dict[str, str] = field(default_factory=dict)

    def get_api_key(self, default_env_var: Optional[str] = None) -> Optional[str]:
        """Get the API key for this provider from environment variables."""
        env_var = self.api_key_env_var or default_env_var
        if env_var:
            api_key = os.getenv(env_var)
            if not api_key:
                raise ValueError(
                    f"API key for provider '{self.name}' not found "
                    f"in environment variable '{env_var}'"
                )
            return api_key
        return None

    def get_all_model_ids(self) -> list[str]:
        """Get a list of all model IDs for this provider, including aliases."""
        model_ids = []
        for model in self.models:
            model_ids.append(model.id)
            model_ids.extend(model.aliases)
        return model_ids

    def resolve_model_id(self, requested_model: str) -> Optional[str]:
        """Resolve a requested model name to a valid model ID for this provider."""
        for model in self.models:
            if requested_model == model.id or requested_model in model.aliases:
                return model.id
        return None

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "ExternalProviderConfig":
        """Create an ExternalProviderConfig from a dictionary (from YAML)."""
        models = [ExternalModelConfig.from_dict(m) for m in data.get("models", [])]
        return ExternalProviderConfig(
            name=data["name"],
            type=data["type"],
            api_base=data["api_base"],
            models=models,
            api_key_env_var=data.get("api_key_env_var"),
            timeout=data.get("timeout", 10.0),
            max_retries=data.get("max_retries", 3),
            custom_headers=data.get("custom_headers", {}),
        )
