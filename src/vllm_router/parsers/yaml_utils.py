from typing import Any

import yaml

from vllm_router.log import init_logger

logger = init_logger(__name__)


def generate_static_backends(models: dict[str, Any]) -> str:
    static_backends = []
    for _, details in models.items():
        if "static_backends" in details:
            static_backends.extend(details["static_backends"])
    return ",".join(static_backends)


def generate_static_models(models: dict[str, Any]) -> str:
    static_models = []
    for name, details in models.items():
        if "static_backends" in details:
            static_models.extend([name] * len(details["static_backends"]))
    return ",".join(static_models)


def generate_static_aliases(aliases: dict[str, Any]) -> str:
    return ",".join(f"{alias}:{model}" for alias, model in aliases.items())


def generate_static_model_types(models: dict[str, Any]) -> str:
    static_model_types = []
    for _, details in models.items():
        if "static_model_type" in details and "static_backends" in details:
            static_model_types.extend(
                [details["static_model_type"]] * len(details["static_backends"])
            )
    return ",".join(static_model_types)


def generate_static_model_max_lens(models: dict[str, Any]) -> str:
    static_model_max_lens = []
    for name, details in models.items():
        if "max_model_len" not in details:
            continue
        max_model_len = details["max_model_len"]
        if (
            not isinstance(max_model_len, int)
            or isinstance(max_model_len, bool)
            or max_model_len <= 0
        ):
            raise ValueError(
                f"max_model_len for model '{name}' must be a positive integer, got {max_model_len!r}"
            )
        static_model_max_lens.append(f"{name}:{max_model_len}")
    return ",".join(static_model_max_lens)


def read_and_process_yaml_config_file(config_path: str) -> dict[str, Any]:
    with open(config_path, encoding="utf-8") as f:
        try:
            yaml_config = yaml.safe_load(f)
            if not yaml_config:
                return {}
            models = yaml_config.pop("static_models", None)
            aliases = yaml_config.pop("static_aliases", None)
            if models:
                yaml_config["static_backends"] = generate_static_backends(models)
                yaml_config["static_models"] = generate_static_models(models)
                yaml_config["static_model_types"] = generate_static_model_types(models)
                max_lens = generate_static_model_max_lens(models)
                if max_lens:
                    yaml_config["static_model_max_lens"] = max_lens
            if aliases:
                yaml_config["static_aliases"] = generate_static_aliases(aliases)
            return yaml_config
        except (yaml.YAMLError, AttributeError) as e:
            logger.error(f"Error loading YAML config file: {e}")
            raise
