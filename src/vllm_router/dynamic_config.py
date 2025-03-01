import json
import threading
import time
from dataclasses import dataclass

from fastapi import FastAPI

from vllm_router.log import init_logger
from vllm_router.routing_logic import ReconfigureRoutingLogic
from vllm_router.service_discovery import (
    ReconfigureServiceDiscovery,
    ServiceDiscoveryType,
)
from vllm_router.utils import SingletonMeta, parse_static_model_names, parse_static_urls

logger = init_logger(__name__)


@dataclass
class DynamicRouterConfig:
    """
    Re-configurable configurations for the VLLM router.
    """

    # Service discovery configurations
    service_discovery_type: str
    static_backends: str
    static_models: str
    k8s_port: int
    k8s_namespace: str
    k8s_label_selector: str

    # Routing logic configurations
    routing_logic: str
    session_key: str

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
            service_discovery_type=args.service_discovery_type,
            static_backends=args.static_backends,
            static_models=args.static_models,
            k8s_port=args.k8s_port,
            k8s_namespace=args.k8s_namespace,
            k8s_label_selector=args.k8s_label_selector,
            # Routing logic configurations
            routing_logic=args.routing_logic,
            session_key=args.session_key,
        )

    @staticmethod
    def from_json(json_path: str) -> "DynamicRouterConfig":
        with open(json_path, "r") as f:
            config = json.load(f)
        return DynamicRouterConfig(**config)

    def to_json_str(self) -> str:
        return json.dumps(self, default=lambda o: o.__dict__, sort_keys=True, indent=4)


class DynamicConfigWatcher(metaclass=SingletonMeta):
    """
    Watches a config json file for changes and updates the DynamicRouterConfig accordingly.
    """

    def __init__(
        self,
        config_json: str,
        watch_interval: int,
        init_config: DynamicRouterConfig,
        app: FastAPI,
    ):
        """
        Initializes the ConfigMapWatcher with the given ConfigMap name and namespace.

        Args:
            config_json: the path to the json file containing the dynamic configuration
            watch_interval: the interval in seconds at which to watch the for changes
            app: the fastapi app to reconfigure
        """
        self.config_json = config_json
        self.watch_interval = watch_interval
        self.init_config = init_config
        self.app = app

        # Watcher thread
        self.running = True
        self.watcher_thread = threading.Thread(target=self._watch_worker)
        self.watcher_thread.start()
        assert hasattr(self.app, "state")

    def reconfigure_service_discovery(self, config: DynamicRouterConfig):
        """
        Reconfigures the router with the given config.
        """

        if config.service_discovery_type == "static":
            ReconfigureServiceDiscovery(
                ServiceDiscoveryType.STATIC,
                urls=parse_static_urls(config.static_backends),
                models=parse_static_model_names(config.static_models),
            )
        elif config.service_discovery_type == "k8s":
            ReconfigureServiceDiscovery(
                ServiceDiscoveryType.K8S,
                namespace=config.k8s_namespace,
                port=config.k8s_port,
                label_selector=config.k8s_label_selector,
            )
        else:
            raise ValueError(
                f"Invalid service discovery type: {config.service_discovery_type}"
            )

        logger.info(f"DynamicConfigWatcher: Service discovery reconfiguration complete")

    def reconfigure_routing_logic(self, config: DynamicRouterConfig):
        """
        Reconfigures the router with the given config.
        """
        routing_logic = ReconfigureRoutingLogic(
            config.routing_logic, session_key=config.session_key
        )
        self.app.state.router = routing_logic
        logger.info(f"DynamicConfigWatcher: Routing logic reconfiguration complete")

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

    def reconfigure_all(self, config: DynamicRouterConfig):
        """
        Reconfigures the router with the given config.
        """
        self.reconfigure_service_discovery(config)
        self.reconfigure_routing_logic(config)
        self.reconfigure_batch_api(config)
        self.reconfigure_stats(config)

    def _watch_worker(self):
        """
        Watches the config file for changes and updates the DynamicRouterConfig accordingly.
        On every watch_interval, it will try loading the config file and compare the changes.
        If the config file has changed, it will reconfigure the system with the new config.
        """
        while self.running:
            try:
                with open(self.config_json, "r") as f:
                    config = json.load(f)
                if config != self.current_config:
                    logger.info(
                        f"DynamicConfigWatcher: Config changed, reconfiguring..."
                    )
                    self.reconfigure_all(config)
                    logger.info(
                        f"DynamicConfigWatcher: Config reconfiguration complete"
                    )
                    self.current_config = config
            except Exception as e:
                logger.warning(f"DynamicConfigWatcher: Error loading config file: {e}")
                time.sleep(self.watch_interval)

    def close(self):
        """
        Closes the watcher thread.
        """
        self.running = False
        self.watcher_thread.join()
        logger.info("DynamicConfigWatcher: Closed")


def InitializeDynamicConfigWatcher(
    config_json: str,
    watch_interval: int,
    init_config: DynamicRouterConfig,
    app: FastAPI,
):
    """
    Initializes the DynamicConfigWatcher with the given config json and watch interval.
    """
    return DynamicConfigWatcher(config_json, watch_interval, init_config, app)


def GetDynamicConfigWatcher() -> DynamicConfigWatcher:
    """
    Returns the DynamicConfigWatcher singleton.
    """
    return DynamicConfigWatcher()
