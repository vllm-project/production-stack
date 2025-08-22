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

import json
import threading
import time
from dataclasses import dataclass
from typing import Literal, Optional

from fastapi import FastAPI

from vllm_router.log import init_logger
from vllm_router.parsers.yaml_utils import (
    read_and_process_yaml_config_file,
)
from vllm_router.routers.routing_logic import reconfigure_routing_logic
from vllm_router.service_discovery import (
    ServiceDiscoveryType,
    reconfigure_service_discovery,
)
from vllm_router.services.callbacks_service.callbacks import configure_custom_callbacks
from vllm_router.utils import (
    SingletonMeta,
    parse_comma_separated_args,
    parse_static_aliases,
    parse_static_urls,
)

logger = init_logger(__name__)


@dataclass
class DynamicRouterConfig:
    """
    Re-configurable configurations for the VLLM router.
    """

    # Required configurations
    service_discovery: str
    routing_logic: str

    # Optional configurations
    # Service discovery configurations
    static_backends: Optional[str] = None
    static_models: Optional[str] = None
    static_aliases: Optional[str] = None
    static_model_labels: Optional[str] = None
    static_model_types: Optional[str] = None
    static_backend_health_checks: Optional[bool] = False
    prefill_model_labels: Optional[str] = None
    decode_model_labels: Optional[str] = None
    k8s_port: Optional[int] = None
    k8s_namespace: Optional[str] = None
    k8s_label_selector: Optional[str] = None

    # Routing logic configurations
    session_key: Optional[str] = None

    # Logging Options
    callbacks: Optional[str] = None

    # Batch API configurations
    # TODO (ApostaC): Support dynamic reconfiguration of batch API
    # enable_batch_api: bool
    # file_storage_class: str
    # file_storage_path: str
    # batch_processor: str

    # Stats configurations
    # TODO (ApostaC): Support dynamic reconfiguration of stats monitor
    # engine_stats_interval: int
    # request_stats_window: int
    # log_stats: bool
    # log_stats_interval: int

    @staticmethod
    def from_args(args) -> "DynamicRouterConfig":
        return DynamicRouterConfig(
            service_discovery=args.service_discovery,
            static_backends=args.static_backends,
            static_models=args.static_models,
            static_model_types=args.static_model_types,
            static_aliases=args.static_aliases,
            k8s_port=args.k8s_port,
            k8s_namespace=args.k8s_namespace,
            k8s_label_selector=args.k8s_label_selector,
            # Routing logic configurations
            routing_logic=args.routing_logic,
            session_key=args.session_key,
            # Logging Options
            callbacks=args.callbacks,
        )

    @staticmethod
    def from_yaml(yaml_path: str) -> "DynamicRouterConfig":
        config = read_and_process_yaml_config_file(yaml_path)
        return DynamicRouterConfig(**config)

    @staticmethod
    def from_json(json_path: str) -> "DynamicRouterConfig":
        with open(json_path, "r") as f:
            config = json.load(f)
        return DynamicRouterConfig(**config)

    def to_json_str(self) -> str:
        return json.dumps(self, default=lambda o: o.__dict__, sort_keys=True, indent=4)


class DynamicConfigWatcher(metaclass=SingletonMeta):
    """
    Watches a config file for changes and updates the DynamicRouterConfig accordingly.
    """

    def __init__(
        self,
        config_path: str,
        config_file_type: Literal["YAML", "JSON"],
        watch_interval: int,
        init_config: DynamicRouterConfig,
        app: FastAPI,
    ):
        """
        Initializes the ConfigMapWatcher with the given ConfigMap name and namespace.

        Args:
            config_path: the path to the config file containing the dynamic configuration
            config_file_type: the config file type containing the dynamic configuration (YAML or JSON)
            watch_interval: the interval in seconds at which to watch the for changes
            app: the fastapi app to reconfigure
        """
        self.config_path = config_path
        self.config_file_type = config_file_type
        self.watch_interval = watch_interval
        self.current_config = init_config
        self.app = app

        # Watcher thread
        self.running = True
        self.watcher_thread = threading.Thread(target=self._watch_worker)
        self.watcher_thread.start()
        assert hasattr(self.app, "state")

    def get_current_config(self) -> DynamicRouterConfig:
        return self.current_config

    def reconfigure_service_discovery(self, config: DynamicRouterConfig):
        """
        Reconfigures the router with the given config.
        """
        if config.service_discovery == "static":
            reconfigure_service_discovery(
                ServiceDiscoveryType.STATIC,
                app=self.app,
                urls=parse_static_urls(config.static_backends),
                models=parse_comma_separated_args(config.static_models),
                aliases=(
                    parse_static_aliases(config.static_aliases)
                    if config.static_aliases
                    else None
                ),
                model_labels=parse_comma_separated_args(config.static_model_labels),
                model_types=parse_comma_separated_args(config.static_model_types),
                static_backend_health_checks=config.static_backend_health_checks,
                prefill_model_labels=parse_comma_separated_args(
                    config.prefill_model_labels
                ),
                decode_model_labels=parse_comma_separated_args(
                    config.decode_model_labels
                ),
            )
        elif config.service_discovery == "k8s":
            reconfigure_service_discovery(
                ServiceDiscoveryType.K8S,
                app=self.app,
                namespace=config.k8s_namespace,
                port=config.k8s_port,
                label_selector=config.k8s_label_selector,
                prefill_model_labels=parse_comma_separated_args(
                    config.prefill_model_labels
                ),
                decode_model_labels=parse_comma_separated_args(
                    config.decode_model_labels
                ),
            )
        else:
            raise ValueError(
                f"Invalid service discovery type: {config.service_discovery}"
            )

        logger.info("DynamicConfigWatcher: Service discovery reconfiguration complete")

    def reconfigure_routing_logic(self, config: DynamicRouterConfig):
        """
        Reconfigures the router with the given config.
        """
        routing_logic = reconfigure_routing_logic(
            config.routing_logic, session_key=config.session_key
        )
        self.app.state.router = routing_logic
        logger.info("DynamicConfigWatcher: Routing logic reconfiguration complete")

    def reconfigure_batch_api(self, config: DynamicRouterConfig):
        """
        Reconfigures the router with the given config.
        """
        # TODO (ApostaC): Implement reconfigure_batch_api
        pass

    def reconfigure_stats(self, config: DynamicRouterConfig):
        """
        Reconfigures the router with the given config.
        """
        # TODO (ApostaC): Implement reconfigure_stats
        pass

    def reconfigure_callbacks(self, config: DynamicRouterConfig):
        """
        Reconfigures the router with the given config.
        """
        if config.callbacks:
            configure_custom_callbacks(config.callbacks, self.app)
        else:
            self.app.state.callbacks = None

    def reconfigure_all(self, config: DynamicRouterConfig):
        """
        Reconfigures the router with the given config.
        """
        self.reconfigure_service_discovery(config)
        self.reconfigure_routing_logic(config)
        self.reconfigure_batch_api(config)
        self.reconfigure_stats(config)
        self.reconfigure_callbacks(config)

    def _sleep_or_break(self, check_interval: float = 1):
        """
        Sleep for self.watch_interval seconds if self.running is True.
        Otherwise, break the loop.
        """
        for _ in range(int(self.watch_interval / check_interval)):
            if not self.running:
                break
            time.sleep(check_interval)

    def _watch_worker(self):
        """
        Watches the config file for changes and updates the DynamicRouterConfig accordingly.
        On every watch_interval, it will try loading the config file and compare the changes.
        If the config file has changed, it will reconfigure the system with the new config.
        """
        while self.running:
            try:
                if self.config_file_type == "YAML":
                    config = DynamicRouterConfig.from_yaml(self.config_path)
                elif self.config_file_type == "JSON":
                    config = DynamicRouterConfig.from_json(self.config_path)
                else:
                    raise ValueError("Unsupported config file type.")
                if config != self.current_config:
                    logger.info(
                        "DynamicConfigWatcher: Config changed, reconfiguring..."
                    )
                    self.reconfigure_all(config)
                    logger.info("DynamicConfigWatcher: Config reconfiguration complete")
                    self.current_config = config
            except Exception as e:
                logger.warning(f"DynamicConfigWatcher: Error loading config file: {e}")

            self._sleep_or_break()

    def close(self):
        """
        Closes the watcher thread.
        """
        self.running = False
        self.watcher_thread.join()
        logger.info("DynamicConfigWatcher: Closed")


def initialize_dynamic_config_watcher(
    config_path: str,
    config_file_type: Literal["YAML", "JSON"],
    watch_interval: int,
    init_config: DynamicRouterConfig,
    app: FastAPI,
):
    """
    Initializes the DynamicConfigWatcher with the given config path, file type and watch interval.
    """
    return DynamicConfigWatcher(
        config_path, config_file_type, watch_interval, init_config, app
    )


def get_dynamic_config_watcher() -> DynamicConfigWatcher:
    """
    Returns the DynamicConfigWatcher singleton.
    """
    return DynamicConfigWatcher(_create=False)
