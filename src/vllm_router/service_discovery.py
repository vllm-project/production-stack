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
import abc
import asyncio
import enum
import hashlib
import os
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional

import httpx
import requests
from kubernetes import client, config, watch

from vllm_router import utils
from vllm_router.log import init_logger

logger = init_logger(__name__)

_global_service_discovery: "Optional[ServiceDiscovery]" = None


class ServiceDiscoveryType(enum.Enum):
    STATIC = "static"
    K8S = "k8s"


@dataclass
class ModelInfo:
    """Information about a model including its relationships and metadata."""

    id: str
    object: str
    created: int = 0
    owned_by: str = "vllm"
    root: Optional[str] = None
    parent: Optional[str] = None
    is_adapter: bool = False

    @classmethod
    def from_dict(cls, data: Dict) -> "ModelInfo":
        """Create a ModelInfo instance from a dictionary."""
        return cls(
            id=data.get("id"),
            object=data.get("object", "model"),
            created=data.get("created", int(time.time())),
            owned_by=data.get("owned_by", "vllm"),
            root=data.get("root", None),
            parent=data.get("parent", None),
            is_adapter=data.get("parent") is not None,
        )

    def to_dict(self) -> Dict:
        """Convert the ModelInfo instance to a dictionary."""
        return {
            "id": self.id,
            "object": self.object,
            "created": self.created,
            "owned_by": self.owned_by,
            "root": self.root,
            "parent": self.parent,
            "is_adapter": self.is_adapter,
        }


@dataclass
class EndpointInfo:
    # Endpoint's url
    url: str

    # Model names
    model_names: List[str]

    # Endpoint Id
    Id: str

    # Added timestamp
    added_timestamp: float

    # Model label
    model_label: str

    # Endpoint's sleep status
    sleep: bool

    # Pod name
    pod_name: Optional[str] = None

    # Service name
    service_name: Optional[str] = None

    # Namespace
    namespace: Optional[str] = None

    # Model information including relationships
    model_info: Dict[str, ModelInfo] = None

    def __str__(self):
        return f"EndpointInfo(url={self.url}, model_names={self.model_names}, added_timestamp={self.added_timestamp}, model_label={self.model_label}, service_name={self.service_name},pod_name={self.pod_name}, namespace={self.namespace})"

    def get_base_models(self) -> List[str]:
        """
        Get the list of base models (models without parents) available on this endpoint.
        """
        if not self.model_info:
            return []
        return [
            model_id for model_id, info in self.model_info.items() if not info.parent
        ]

    def get_adapters(self) -> List[str]:
        """
        Get the list of adapters (models with parents) available on this endpoint.
        """
        if not self.model_info:
            return []
        return [model_id for model_id, info in self.model_info.items() if info.parent]

    def get_adapters_for_model(self, base_model: str) -> List[str]:
        """
        Get the list of adapters available for a specific base model.

        Args:
            base_model: The ID of the base model

        Returns:
            List of adapter IDs that are based on the specified model
        """
        if not self.model_info:
            return []
        return [
            model_id
            for model_id, info in self.model_info.items()
            if info.parent == base_model
        ]

    def has_model(self, model_id: str) -> bool:
        """
        Check if a specific model (base model or adapter) is available on this endpoint.

        Args:
            model_id: The ID of the model to check

        Returns:
            True if the model is available, False otherwise
        """
        return model_id in self.model_names

    def get_model_info(self, model_id: str) -> Optional[ModelInfo]:
        """
        Get detailed information about a specific model.

        Args:
            model_id: The ID of the model to get information for

        Returns:
            ModelInfo object containing model information if available, None otherwise
        """
        if not self.model_info:
            return None
        return self.model_info.get(model_id)


class ServiceDiscovery(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def get_endpoint_info(self) -> List[EndpointInfo]:
        """
        Get the URLs of the serving engines that are available for
        querying.

        Returns:
            a list of engine URLs
        """
        pass

    def get_health(self) -> bool:
        """
        Check if the service discovery module is healthy.

        Returns:
            True if the service discovery module is healthy, False otherwise
        """
        return True

    def close(self) -> None:
        """
        Close the service discovery module.
        """
        pass


class StaticServiceDiscovery(ServiceDiscovery):
    def __init__(
        self,
        app,
        urls: List[str],
        models: List[str],
        aliases: List[str] | None = None,
        model_labels: List[str] | None = None,
        model_types: List[str] | None = None,
        static_backend_health_checks: bool = False,
        prefill_model_labels: List[str] | None = None,
        decode_model_labels: List[str] | None = None,
    ):
        self.app = app
        assert len(urls) == len(models), "URLs and models should have the same length"
        self.urls = urls
        self.models = models
        self.aliases = aliases
        self.model_labels = model_labels
        self.model_types = model_types
        self.engines_id = [str(uuid.uuid4()) for i in range(0, len(urls))]
        self.added_timestamp = int(time.time())
        self.unhealthy_endpoint_hashes = []
        if static_backend_health_checks:
            self.start_health_check_task()
        self.prefill_model_labels = prefill_model_labels
        self.decode_model_labels = decode_model_labels

    def get_unhealthy_endpoint_hashes(self) -> list[str]:
        unhealthy_endpoints = []
        for url, model, model_type in zip(self.urls, self.models, self.model_types):
            if utils.is_model_healthy(url, model, model_type):
                logger.debug(f"{model} at {url} is healthy")
            else:
                logger.warning(f"{model} at {url} not healthy!")
                unhealthy_endpoints.append(self.get_model_endpoint_hash(url, model))
        return unhealthy_endpoints

    async def check_model_health(self):
        while True:
            try:
                self.unhealthy_endpoint_hashes = self.get_unhealthy_endpoint_hashes()
                time.sleep(60)
            except Exception as e:
                logger.error(e)

    def start_health_check_task(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        asyncio.run_coroutine_threadsafe(self.check_model_health(), self.loop)
        logger.info("Health check thread started")

    def get_model_endpoint_hash(self, url: str, model: str) -> str:
        return hashlib.md5(f"{url}{model}".encode()).hexdigest()

    def _get_model_info(self, model: str) -> Dict[str, ModelInfo]:
        """
        Get detailed model information. For static serving engines, we don't query the engine, instead we use predefined
        static model info.

        Args:
            model: the model name

        Returns:
            Dictionary mapping model IDs to their information, including parent-child relationships
        """
        return {
            model: ModelInfo(
                id=model,
                object="model",
                owned_by="vllm",
                parent=None,
                is_adapter=False,
                root=None,
                created=int(time.time()),
            )
        }

    def get_endpoint_info(self) -> List[EndpointInfo]:
        """
        Get the URLs of the serving engines that are available for
        querying.

        Returns:
            a list of engine URLs
        """
        endpoint_infos = []
        for i, (url, model) in enumerate(zip(self.urls, self.models)):
            if (
                self.get_model_endpoint_hash(url, model)
                in self.unhealthy_endpoint_hashes
            ):
                continue
            model_label = self.model_labels[i] if self.model_labels else "default"
            endpoint_info = EndpointInfo(
                url=url,
                model_names=[model],  # Convert single model to list
                Id=self.engines_id[i],
                sleep=False,
                added_timestamp=self.added_timestamp,
                model_label=model_label,
                model_info=self._get_model_info(model),
            )
            endpoint_infos.append(endpoint_info)
        if (
            self.prefill_model_labels is not None
            and self.decode_model_labels is not None
        ):
            for endpoint_info in endpoint_infos:
                if endpoint_info.model_label in self.prefill_model_labels:
                    self.app.state.prefill_client = httpx.AsyncClient(
                        base_url=endpoint_info.url,
                        timeout=None,
                    )
                elif endpoint_info.model_label in self.decode_model_labels:
                    self.app.state.decode_client = httpx.AsyncClient(
                        base_url=endpoint_info.url,
                        timeout=None,
                    )
        return endpoint_infos


class K8sPodIPServiceDiscovery(ServiceDiscovery):
    def __init__(
        self,
        app,
        namespace: str,
        port: str,
        label_selector=None,
        prefill_model_labels: List[str] | None = None,
        decode_model_labels: List[str] | None = None,
    ):
        """
        Initialize the Kubernetes service discovery module. This module
        assumes all serving engine pods are in the same namespace, listening
        on the same port, and have the same label selector.

        It will start a daemon thread to watch the engine pods and update
        the url of the available engines.

        Args:
            namespace: the namespace of the engine pods
            port: the port of the engines
            label_selector: the label selector of the engines
        """
        self.app = app
        self.namespace = namespace
        self.port = port
        self.available_engines: Dict[str, EndpointInfo] = {}
        self.available_engines_lock = threading.Lock()
        self.label_selector = label_selector

        # Init kubernetes watcher
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()

        self.k8s_api = client.CoreV1Api()
        self.k8s_watcher = watch.Watch()

        # Start watching engines
        self.running = True
        self.watcher_thread = threading.Thread(target=self._watch_engines, daemon=True)
        self.watcher_thread.start()
        self.prefill_model_labels = prefill_model_labels
        self.decode_model_labels = decode_model_labels

    @staticmethod
    def _check_pod_ready(container_statuses):
        """
        Check if all containers in the pod are ready by reading the
        k8s container statuses.
        """
        if not container_statuses:
            return False
        ready_count = sum(1 for status in container_statuses if status.ready)
        return ready_count == len(container_statuses)

    def _get_engine_sleep_status(self, pod_ip) -> Optional[bool]:
        """
        Get the engine sleeping status by querying the engine's
        '/is_sleeping' endpoint.

        Args:
            pod_ip: the IP address of the pod running the engine

        Returns:
            the sleep status of the target engine
        """
        url = f"http://{pod_ip}:{self.port}/is_sleeping"
        try:
            headers = None
            if VLLM_API_KEY := os.getenv("VLLM_API_KEY"):
                logger.info("Using vllm server authentication")
                headers = {"Authorization": f"Bearer {VLLM_API_KEY}"}
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            sleep = response.json()["is_sleeping"]
            return sleep
        except Exception as e:
            logger.warning(
                f"Failed to get the sleep status for engine at {url} - sleep status is set to `False`: {e}"
            )
            return False

    def _check_engine_sleep_mode(self, pod_name) -> Optional[bool]:
        try:
            enable_sleep_mode = False
            pod = self.k8s_api.read_namespaced_pod(
                name=pod_name, namespace=self.namespace
            )
            for container in pod.spec.containers:
                if container.name == "vllm":
                    for arg in container.command:
                        if arg == "--enable-sleep-mode":
                            enable_sleep_mode = True
                            break
            return enable_sleep_mode
        except client.rest.ApiException as e:
            logger.error(
                f"Error checking if sleep-mode is enable for pod {pod_name}: {e}"
            )
            return False

    def add_sleep_label(self, pod_name):
        try:
            pod = self.k8s_api.read_namespaced_pod(
                name=pod_name, namespace=self.namespace
            )
            # pod.metadata.labels = {"sleeping": "true"}
            pod.metadata.labels.update({"sleeping": "true"})
            self.k8s_api.patch_namespaced_pod(
                name=pod_name, namespace=self.namespace, body=pod
            )
            logger.info(f"Sleeping label added to the pod: {pod_name}")

        except client.rest.ApiException as e:
            logger.error(f"Error adding sleeping label to the pod {pod_name}: {e}")

    def remove_sleep_label(self, pod_name):
        try:
            label_key = "sleeping"
            body = {"metadata": {"labels": {label_key: None}}}

            pod = self.k8s_api.read_namespaced_pod(
                name=pod_name, namespace=self.namespace
            )
            if label_key in pod.metadata.labels:
                self.k8s_api.patch_namespaced_pod(
                    name=pod_name, namespace=self.namespace, body=body
                )
                logger.info(f"Label `sleeping=true` removed from pod '{pod_name}'")
            else:
                logger.info(
                    f"Label `sleeping=true` not found on pod '{pod_name}' in namespace '{self.namespace}'"
                )

        except client.rest.ApiException as e:
            logger.error(f"Error removing sleeping label: {e}")

    def _get_model_names(self, pod_ip) -> List[str]:
        """
        Get the model names of the serving engine pod by querying the pod's
        '/v1/models' endpoint.

        Args:
            pod_ip: the IP address of the pod

        Returns:
            List of model names available on the serving engine, including both base models and adapters
        """
        url = f"http://{pod_ip}:{self.port}/v1/models"
        try:
            headers = None
            if VLLM_API_KEY := os.getenv("VLLM_API_KEY"):
                logger.info("Using vllm server authentication")
                headers = {"Authorization": f"Bearer {VLLM_API_KEY}"}
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            models = response.json()["data"]

            # Collect all model names, including both base models and adapters
            model_names = []
            for model in models:
                model_id = model["id"]
                model_names.append(model_id)

            logger.info(f"Found models on pod {pod_ip}: {model_names}")
            return model_names
        except Exception as e:
            logger.error(f"Failed to get model names from {url}: {e}")
            return []

    def _get_model_info(self, pod_ip) -> Dict[str, ModelInfo]:
        """
        Get detailed model information from the serving engine pod.

        Args:
            pod_ip: the IP address of the pod

        Returns:
            Dictionary mapping model IDs to their ModelInfo objects, including parent-child relationships
        """
        url = f"http://{pod_ip}:{self.port}/v1/models"
        try:
            headers = None
            if VLLM_API_KEY := os.getenv("VLLM_API_KEY"):
                logger.info("Using vllm server authentication")
                headers = {"Authorization": f"Bearer {VLLM_API_KEY}"}
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            models = response.json()["data"]
            # Create a dictionary of model information
            model_info = {}
            for model in models:
                model_id = model["id"]
                model_info[model_id] = ModelInfo.from_dict(model)

            return model_info
        except Exception as e:
            logger.error(f"Failed to get model info from {url}: {e}")
            return {}

    def _get_model_label(self, pod) -> Optional[str]:
        """
        Get the model label from the pod's metadata labels.

        Args:
            pod: The Kubernetes pod object

        Returns:
            The model label if found, None otherwise
        """
        if not pod.metadata.labels:
            return None
        return pod.metadata.labels.get("model")

    def _watch_engines(self):
        # TODO (ApostaC): remove the hard-coded timeouts

        while self.running:
            try:
                for event in self.k8s_watcher.stream(
                    self.k8s_api.list_namespaced_pod,
                    namespace=self.namespace,
                    label_selector=self.label_selector,
                    timeout_seconds=30,
                ):
                    pod = event["object"]
                    event_type = event["type"]
                    pod_name = pod.metadata.name
                    pod_ip = pod.status.pod_ip
                    is_pod_ready = self._check_pod_ready(pod.status.container_statuses)
                    if is_pod_ready:
                        model_names = self._get_model_names(pod_ip)
                        model_label = self._get_model_label(pod)
                    else:
                        model_names = []
                        model_label = None
                    self._on_engine_update(
                        pod_name,
                        pod_ip,
                        event_type,
                        is_pod_ready,
                        model_names,
                        model_label,
                    )
            except Exception as e:
                logger.error(f"K8s watcher error: {e}")
                time.sleep(0.5)

    def _add_engine(
        self, engine_name: str, engine_ip: str, model_names: List[str], model_label: str
    ):
        logger.info(
            f"Discovered new serving engine {engine_name} at "
            f"{engine_ip}, running models: {model_names}"
        )

        # Get detailed model information
        model_info = self._get_model_info(engine_ip)

        # Check if engine is enabled with sleep mode and set engine sleep status
        if self._check_engine_sleep_mode(engine_name):
            sleep_status = self._get_engine_sleep_status(engine_ip)
        else:
            sleep_status = False

        with self.available_engines_lock:
            self.available_engines[engine_name] = EndpointInfo(
                url=f"http://{engine_ip}:{self.port}",
                model_names=model_names,
                added_timestamp=int(time.time()),
                Id=str(uuid.uuid5(uuid.NAMESPACE_DNS, engine_name)),
                model_label=model_label,
                sleep=sleep_status,
                pod_name=engine_name,
                namespace=self.namespace,
                model_info=model_info,
            )
            if (
                self.prefill_model_labels is not None
                and self.decode_model_labels is not None
            ):
                if model_label in self.prefill_model_labels:
                    self.app.state.prefill_client = httpx.AsyncClient(
                        base_url=f"http://{engine_ip}:{self.port}",
                        timeout=None,
                    )
                elif model_label in self.decode_model_labels:
                    self.app.state.decode_client = httpx.AsyncClient(
                        base_url=f"http://{engine_ip}:{self.port}",
                        timeout=None,
                    )
            # Store model information in the endpoint info
            self.available_engines[engine_name].model_info = model_info

    def _delete_engine(self, engine_name: str):
        logger.info(f"Serving engine {engine_name} is deleted")
        with self.available_engines_lock:
            del self.available_engines[engine_name]

    def _on_engine_update(
        self,
        engine_name: str,
        engine_ip: Optional[str],
        event: str,
        is_pod_ready: bool,
        model_names: List[str],
        model_label: Optional[str],
    ) -> None:
        if event == "ADDED":
            if engine_ip is None:
                return

            if not is_pod_ready:
                return

            if not model_names:
                return

            self._add_engine(engine_name, engine_ip, model_names, model_label)

        elif event == "DELETED":
            if engine_name not in self.available_engines:
                return

            self._delete_engine(engine_name)

        elif event == "MODIFIED":
            if engine_ip is None:
                return

            if is_pod_ready and model_names:
                self._add_engine(engine_name, engine_ip, model_names, model_label)
                return

            if (
                not is_pod_ready or not model_names
            ) and engine_name in self.available_engines:
                self._delete_engine(engine_name)
                return

    def get_endpoint_info(self) -> List[EndpointInfo]:
        """
        Get the URLs of the serving engines that are available for
        querying.

        Returns:
            a list of engine URLs
        """
        with self.available_engines_lock:
            return list(self.available_engines.values())

    def get_health(self) -> bool:
        """
        Check if the service discovery module is healthy.

        Returns:
            True if the service discovery module is healthy, False otherwise
        """
        return self.watcher_thread.is_alive()

    def close(self):
        """
        Close the service discovery module.
        """
        self.running = False
        self.k8s_watcher.stop()
        self.watcher_thread.join()


class K8sServiceNameServiceDiscovery(ServiceDiscovery):
    def __init__(
        self,
        app,
        namespace: str,
        port: str,
        label_selector=None,
        prefill_model_labels: List[str] | None = None,
        decode_model_labels: List[str] | None = None,
    ):
        """
        Initialize the Kubernetes service discovery module. This module
        assumes all serving engine services are in the same namespace, listening
        on the same port, and have the same label selector.

        For the routing logic, this approach cannot perform advanced routing
        strategies such as kvaware or PD routing. Instead, it relies on
        Kubernetes'native service-level load-balancing mechanisms, such
        as round-robin or session affinity-based routing.

        Regarding metrics collection, the monitoring system typically scrapes vLLM
        metrics directly from individual pods. When metrics collection is performed
        at the service level, there is no guarantee that the collected metrics
        correspond to the specific pod that handled a given inference request,
        especially in multi-replica deployments.

        Therefore, to ensure full functionality of the production stack including
        accurate routing and metrics, this service discovery mechanismis recommended
        for deployments where each service maps to a single pod(1:1 service-to-pod ratio).

        It will start a daemon thread to watch the engine services and update
        the url of the available engines.

        Args:
            namespace: the namespace of the engine services
            port: the port of the engines
            label_selector: the label selector of the engines
        """
        self.app = app
        self.namespace = namespace
        self.port = port
        self.available_engines: Dict[str, EndpointInfo] = {}
        self.available_engines_lock = threading.Lock()
        self.label_selector = label_selector

        # Init kubernetes watcher
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()

        self.k8s_api = client.CoreV1Api()
        self.k8s_watcher = watch.Watch()

        # Start watching engines
        self.running = True
        self.watcher_thread = threading.Thread(target=self._watch_engines, daemon=True)
        self.watcher_thread.start()
        self.prefill_model_labels = prefill_model_labels
        self.decode_model_labels = decode_model_labels

    def _check_service_ready(self, service_name, namespace):
        endpoints = self.k8s_api.read_namespaced_endpoints(service_name, namespace)
        if not endpoints.subsets:
            return False

        for subset in endpoints.subsets:
            if subset.addresses:
                return True
        return False

    def _get_engine_sleep_status(self, service_name) -> Optional[bool]:
        """
        Get the engine sleeping status by querying the engine's
        '/is_sleeping' endpoint.

        Args:
            service_name: the name of the service running the engine

        Returns:
            the sleep status of the target engine
        """
        url = f"http://{service_name}:{self.port}/is_sleeping"
        try:
            headers = None
            if VLLM_API_KEY := os.getenv("VLLM_API_KEY"):
                logger.info("Using vllm server authentication")
                headers = {"Authorization": f"Bearer {VLLM_API_KEY}"}
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            sleep = response.json()["is_sleeping"]
            return sleep
        except Exception as e:
            logger.warning(
                f"Failed to get the sleep status for engine at {url} - sleep status is set to `False`: {e}"
            )
            return False

    def _check_engine_sleep_mode(self, service_name) -> Optional[bool]:
        try:
            service = self.k8s_api.read_namespaced_service(service_name, self.namespace)
            if not service.spec.selector:
                return False

            selector = ",".join([f"{k}={v}" for k, v in service.spec.selector.items()])
            pods = self.k8s_api.list_namespaced_pod(
                namespace=self.namespace, label_selector=selector
            )

            if not pods.items:
                logger.warning(
                    f"No pods found for service {service_name} in namespace {self.namespace}"
                )
                return False

            enable_sleep_mode = False
            for container in pods.items[0].spec.containers:
                if container.name == "vllm":
                    for arg in container.command:
                        if arg == "--enable-sleep-mode":
                            enable_sleep_mode = True
                            break
            return enable_sleep_mode
        except client.rest.ApiException as e:
            logger.error(
                f"Error checking if sleep-mode is enable for service {service_name}: {e}"
            )
            return False

    def add_sleep_label(self, service_name):
        try:
            body = {"metadata": {"labels": {"sleeping": "true"}}}
            self.k8s_api.patch_namespaced_service(
                name=service_name, namespace=self.namespace, body=body
            )
            logger.info(f"Sleeping label added to the service: {service_name}")

        except client.rest.ApiException as e:
            logger.error(
                f"Error adding sleeping label to the service {service_name}: {e}"
            )

    def remove_sleep_label(self, service_name):
        try:
            label_key = "sleeping"
            body = {"metadata": {"labels": {label_key: None}}}

            service = self.k8s_api.read_namespaced_service(
                name=service_name, namespace=self.namespace
            )
            if label_key in service.metadata.labels:
                self.k8s_api.patch_namespaced_service(
                    name=service_name, namespace=self.namespace, body=body
                )
                logger.info(
                    f"Label `sleeping=true` removed from service '{service_name}'"
                )
            else:
                logger.info(
                    f"Label `sleeping=true` not found on service '{service_name}' in namespace '{self.namespace}'"
                )

        except client.rest.ApiException as e:
            logger.error(f"Error removing sleeping label: {e}")

    def _get_model_names(self, service_name) -> List[str]:
        """
        Get the model names of the serving engine service by querying the service's
        '/v1/models' endpoint.

        Args:
            service_name: the name of the service

        Returns:
            List of model names available on the serving engine, including both base models and adapters
        """
        url = f"http://{service_name}:{self.port}/v1/models"
        try:
            headers = None
            if VLLM_API_KEY := os.getenv("VLLM_API_KEY"):
                logger.info("Using vllm server authentication")
                headers = {"Authorization": f"Bearer {VLLM_API_KEY}"}
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            models = response.json()["data"]

            # Collect all model names, including both base models and adapters
            model_names = []
            for model in models:
                model_id = model["id"]
                model_names.append(model_id)

            logger.info(f"Found models on service {service_name}: {model_names}")
            return model_names
        except Exception as e:
            logger.error(f"Failed to get model names from {url}: {e}")
            return []

    def _get_model_info(self, service_name) -> Dict[str, ModelInfo]:
        """
        Get detailed model information from the serving engine service.

        Args:
            service_name: the IP name of the service

        Returns:
            Dictionary mapping model IDs to their ModelInfo objects, including parent-child relationships
        """
        url = f"http://{service_name}:{self.port}/v1/models"
        try:
            headers = None
            if VLLM_API_KEY := os.getenv("VLLM_API_KEY"):
                logger.info("Using vllm server authentication")
                headers = {"Authorization": f"Bearer {VLLM_API_KEY}"}
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            models = response.json()["data"]
            # Create a dictionary of model information
            model_info = {}
            for model in models:
                model_id = model["id"]
                model_info[model_id] = ModelInfo.from_dict(model)

            return model_info
        except Exception as e:
            logger.error(f"Failed to get model info from {url}: {e}")
            return {}

    def _get_model_label(self, service) -> Optional[str]:
        """
        Get the model label from the service's selector.

        Args:
            service: The Kubernetes service object

        Returns:
            The model selector if found, None otherwise
        """
        if not service.spec.selector:
            return None
        return service.spec.selector.get("model")

    def _watch_engines(self):
        # TODO (ApostaC): remove the hard-coded timeouts

        while self.running:
            try:
                for event in self.k8s_watcher.stream(
                    self.k8s_api.list_namespaced_service,
                    namespace=self.namespace,
                    label_selector=self.label_selector,
                    timeout_seconds=30,
                ):
                    service = event["object"]
                    event_type = event["type"]
                    service_name = service.metadata.name
                    is_service_ready = self._check_service_ready(
                        service_name, self.namespace
                    )
                    if is_service_ready:
                        model_names = self._get_model_names(service_name)
                        model_label = self._get_model_label(service)
                    else:
                        model_names = []
                        model_label = None
                    self._on_engine_update(
                        service_name,
                        event_type,
                        is_service_ready,
                        model_names,
                        model_label,
                    )
            except Exception as e:
                logger.error(f"K8s watcher error: {e}")
                time.sleep(0.5)

    def _add_engine(self, engine_name: str, model_names: List[str], model_label: str):
        logger.info(
            f"Discovered new serving engine {engine_name} at "
            f"running models: {model_names}"
        )

        # Get detailed model information
        model_info = self._get_model_info(engine_name)

        # Check if engine is enabled with sleep mode and set engine sleep status
        if self._check_engine_sleep_mode(engine_name):
            sleep_status = self._get_engine_sleep_status(engine_name)
        else:
            sleep_status = False

        with self.available_engines_lock:
            self.available_engines[engine_name] = EndpointInfo(
                url=f"http://{engine_name}:{self.port}",
                model_names=model_names,
                added_timestamp=int(time.time()),
                Id=str(uuid.uuid5(uuid.NAMESPACE_DNS, engine_name)),
                model_label=model_label,
                sleep=sleep_status,
                service_name=engine_name,
                namespace=self.namespace,
                model_info=model_info,
            )
            if (
                self.prefill_model_labels is not None
                and self.decode_model_labels is not None
            ):
                if model_label in self.prefill_model_labels:
                    self.app.state.prefill_client = httpx.AsyncClient(
                        base_url=f"http://{engine_name}:{self.port}",
                        timeout=None,
                    )
                elif model_label in self.decode_model_labels:
                    self.app.state.decode_client = httpx.AsyncClient(
                        base_url=f"http://{engine_name}:{self.port}",
                        timeout=None,
                    )
            # Store model information in the endpoint info
            self.available_engines[engine_name].model_info = model_info

    def _delete_engine(self, engine_name: str):
        logger.info(f"Serving engine {engine_name} is deleted")
        with self.available_engines_lock:
            del self.available_engines[engine_name]

    def _on_engine_update(
        self,
        engine_name: str,
        event: str,
        is_service_ready: bool,
        model_names: List[str],
        model_label: Optional[str],
    ) -> None:
        if event == "ADDED":
            if not engine_name:
                return

            if not is_service_ready:
                return

            if not model_names:
                return

            self._add_engine(engine_name, model_names, model_label)

        elif event == "DELETED":
            if engine_name not in self.available_engines:
                return

            self._delete_engine(engine_name)

        elif event == "MODIFIED":
            if not engine_name:
                return

            if is_service_ready and model_names:
                self._add_engine(engine_name, model_names, model_label)
                return

            if (
                not is_service_ready or not model_names
            ) and engine_name in self.available_engines:
                self._delete_engine(engine_name)
                return

    def get_endpoint_info(self) -> List[EndpointInfo]:
        """
        Get the URLs of the serving engines that are available for
        querying.

        Returns:
            a list of engine URLs
        """
        with self.available_engines_lock:
            return list(self.available_engines.values())

    def get_health(self) -> bool:
        """
        Check if the service discovery module is healthy.

        Returns:
            True if the service discovery module is healthy, False otherwise
        """
        return self.watcher_thread.is_alive()

    def close(self):
        """
        Close the service discovery module.
        """
        self.running = False
        self.k8s_watcher.stop()
        self.watcher_thread.join()


def _create_service_discovery(
    service_discovery_type: ServiceDiscoveryType, *args, **kwargs
) -> ServiceDiscovery:
    """
    Create a service discovery module with the given type and arguments.

    Args:
        service_discovery_type: the type of service discovery module
        *args: positional arguments for the service discovery module
        **kwargs: keyword arguments for the service discovery module

    Returns:
        the created service discovery module
    """

    if service_discovery_type == ServiceDiscoveryType.STATIC:
        return StaticServiceDiscovery(*args, **kwargs)
    elif service_discovery_type == ServiceDiscoveryType.K8S:
        k8s_discovery_type = kwargs.pop("k8s_service_discovery_type", "pod-ip")
        if k8s_discovery_type is None or not k8s_discovery_type.strip():
            normalized_type = "pod-ip"
        else:
            normalized_type = k8s_discovery_type.strip().lower()

        if normalized_type == "service-name":
            return K8sServiceNameServiceDiscovery(*args, **kwargs)
        else:
            return K8sPodIPServiceDiscovery(*args, **kwargs)
    else:
        raise ValueError("Invalid service discovery type")


def initialize_service_discovery(
    service_discovery_type: ServiceDiscoveryType, *args, **kwargs
) -> ServiceDiscovery:
    """
    Initialize the service discovery module with the given type and arguments.

    Args:
        service_discovery_type: the type of service discovery module
        *args: positional arguments for the service discovery module
        **kwargs: keyword arguments for the service discovery module

    Returns:
        the initialized service discovery module

    Raises:
        ValueError: if the service discovery module is already initialized
        ValueError: if the service discovery type is invalid
    """
    global _global_service_discovery
    if _global_service_discovery is not None:
        raise ValueError("Service discovery module already initialized")

    _global_service_discovery = _create_service_discovery(
        service_discovery_type, *args, **kwargs
    )
    return _global_service_discovery


def reconfigure_service_discovery(
    service_discovery_type: ServiceDiscoveryType, *args, **kwargs
) -> ServiceDiscovery:
    """
    Reconfigure the service discovery module with the given type and arguments.
    """
    global _global_service_discovery
    if _global_service_discovery is None:
        raise ValueError("Service discovery module not initialized")

    new_service_discovery = _create_service_discovery(
        service_discovery_type, *args, **kwargs
    )

    _global_service_discovery.close()
    _global_service_discovery = new_service_discovery
    return _global_service_discovery


def get_service_discovery() -> ServiceDiscovery:
    """
    Get the initialized service discovery module.

    Returns:
        the initialized service discovery module

    Raises:
        ValueError: if the service discovery module is not initialized
    """
    global _global_service_discovery
    if _global_service_discovery is None:
        raise ValueError("Service discovery module not initialized")

    return _global_service_discovery


if __name__ == "__main__":
    # Test the service discovery
    # k8s_sd = K8sServiceDiscovery("default", 8000, "release=test")
    initialize_service_discovery(
        ServiceDiscoveryType.K8S,
        namespace="default",
        port=8000,
        label_selector="release=test",
    )

    k8s_sd = get_service_discovery()

    time.sleep(1)
    while True:
        urls = k8s_sd.get_endpoint_info()
        print(urls)
        time.sleep(2)
