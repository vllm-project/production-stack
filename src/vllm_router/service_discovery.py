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
import enum
import os
import threading
import time
import asyncio
from asyncio import Task
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import aiohttp
from kubernetes import client, config, watch

from vllm_router.log import init_logger

logger = init_logger(__name__)

_global_service_discovery: "Optional[ServiceDiscovery]" = None


class ServiceDiscoveryType(enum.Enum):
    STATIC = "static"
    K8S = "k8s"


@dataclass
class EndpointInfo:
    # Endpoint's url
    url: str

    # Model name
    model_name: str

    # Added timestamp
    added_timestamp: float


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
    def __init__(self, urls: List[str], models: List[str]):
        assert len(urls) == len(models), "URLs and models should have the same length"
        self.urls = urls
        self.models = models
        self.added_timestamp = int(time.time())

    def get_endpoint_info(self) -> List[EndpointInfo]:
        """
        Get the URLs of the serving engines that are available for
        querying.

        Returns:
            a list of engine URLs
        """
        return [EndpointInfo(url, model, self.added_timestamp) for url, model in zip(self.urls, self.models)]


class K8sServiceDiscovery(ServiceDiscovery):
    def __init__(self, namespace: str, port: str, label_selector=None):
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
        self.namespace = namespace
        self.port = port
        self.available_engines: Dict[Tuple[str, str], EndpointInfo] = {}
        self.available_engines_lock = threading.Lock()
        self.label_selector = label_selector

        # Create an event loop for async operations
        self.loop = asyncio.new_event_loop()

        # Dictionary to track pending async tasks for model discovery
        self.pending_discoveries: Dict[str, Task] = {}
        self.pending_discoveries_lock = threading.Lock()

        # Health tracking
        self.last_health_check = time.time()
        self.last_health_status = True
        self.health_check_interval = 5  # seconds

        # Start a daemon thread to run the event loop
        self.event_loop_thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self.event_loop_thread.start()

        # Create a shared aiohttp session
        self._init_aiohttp_session()

        # Init kubernetes watcher
        try:
            config.load_incluster_config()
        except:
            config.load_kube_config()

        self.k8s_api = client.CoreV1Api()
        self.k8s_watcher = watch.Watch()

        # Start watching engines
        self.running = True
        self.watcher_thread = threading.Thread(target=self._watch_engines, daemon=True)
        self.watcher_thread.start()

    def _init_aiohttp_session(self):
        """Initialize the aiohttp session in the event loop thread"""
        future = asyncio.run_coroutine_threadsafe(self._create_aiohttp_session(), self.loop)
        future.result(timeout=10)  # Wait for session creation with timeout

    async def _create_aiohttp_session(self):
        """Create an aiohttp ClientSession for reuse"""
        # Create a session with connection limits and shorter timeouts
        conn_timeout = aiohttp.ClientTimeout(total=3, connect=1, sock_connect=1, sock_read=2)
        connector = aiohttp.TCPConnector(
            limit=20,  # Maximum number of connections
            limit_per_host=2,  # Maximum number of connections per host
            ttl_dns_cache=300,  # Cache DNS results for 5 minutes
            force_close=False,  # Keep connections alive when possible
        )
        self.session = aiohttp.ClientSession(timeout=conn_timeout, connector=connector)

    def _run_event_loop(self):
        """Run the asyncio event loop in a separate thread"""
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_forever()
        except Exception as e:
            logger.error(f"Event loop error: {e}")
        finally:
            # Clean up any remaining tasks
            pending = asyncio.all_tasks(self.loop)
            for task in pending:
                task.cancel()
            # Wait for tasks to cancel
            if pending:
                self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            # Close the loop
            self.loop.close()
            logger.info("Async event loop closed")

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

    async def _get_model_names_async(self, pod_ip) -> Optional[List[str]]:
        """
        Get the model names of the serving engine pod by querying the pod's
        '/v1/models' endpoint. A pod can serve multiple models (e.g., base + LoRAs).

        This method uses async HTTP requests.

        Args:
            pod_ip: the IP address of the pod

        Returns:
            A list of model names served by the engine, or None if an error occurs or no models found.
        """
        url = f"http://{pod_ip}:{self.port}/v1/models"
        model_names_list: List[str] = []
        try:
            headers = None
            if VLLM_API_KEY := os.getenv("VLLM_API_KEY"):
                logger.info(f"Using vllm server authentication for {url}")
                headers = {"Authorization": f"Bearer {VLLM_API_KEY}"}

            # Use a shorter timeout to avoid blocking for too long during health checks
            timeout = aiohttp.ClientTimeout(total=2.0, connect=1.0, sock_connect=1.0, sock_read=1.5)

            # Explicitly pass timeout to ensure we don't block too long
            async with self.session.get(url, headers=headers, timeout=timeout) as response:
                if response.status >= 400:
                    logger.warning(f"Error response from {url}: {response.status}")
                    return None

                try:
                    response_text = await response.text()
                    response_json = await response.json()
                    data = response_json.get("data")
                except asyncio.TimeoutError:
                    logger.warning(f"Timeout when parsing response from {url}")
                    return None
                except Exception as e:
                    logger.warning(f"Failed to parse JSON from {url}: {e}, response: {response_text[:100]}")
                    return None

                if isinstance(data, list):
                    for model_entry in data:
                        if isinstance(model_entry, dict) and "id" in model_entry and model_entry["id"]:
                            model_names_list.append(model_entry["id"])

                if not model_names_list:
                    logger.warning(f"No model IDs found in response from {url}")
                    if data is None or not isinstance(data, list):
                        return None
                    # Empty but valid response - return empty list
                    return []

        except asyncio.TimeoutError:
            logger.warning(f"Timeout when getting model names from {url}")
            return None
        except aiohttp.ClientConnectorError as e:
            logger.warning(f"Connection error when getting model names from {url}: {e}")
            return None
        except aiohttp.ClientError as e:
            logger.warning(f"Request failed to get model names from {url}: {e}")
            return None
        except Exception as e:
            logger.warning(f"Unexpected error when getting model names from {url}: {e}")
            return None

        return model_names_list

    async def _async_discover_models(self, pod_name: str, pod_ip: str, event_type: str, is_pod_ready: bool):
        """
        Asynchronously discover models for a pod and update the available engines using
        async/await for HTTP requests.

        Args:
            pod_name: Name of the pod
            pod_ip: IP address of the pod
            event_type: Kubernetes event type ("ADDED", "MODIFIED", "DELETED")
            is_pod_ready: Whether the pod is marked as ready
        """
        try:
            # Get model names from the pod
            model_names_reported = await self._get_model_names_async(pod_ip)

            # Process the results with the main event handling logic
            with self.available_engines_lock:
                self._on_engine_update(pod_name, pod_ip, event_type, is_pod_ready, model_names_reported)

        except Exception as e:
            logger.error(f"Error in async model discovery for pod {pod_name}: {str(e)}")
            # Don't update engine info on unexpected exceptions - better to keep old state than corrupt it
        finally:
            # Remove this future from the pending discoveries
            with self.pending_discoveries_lock:
                if pod_name in self.pending_discoveries:
                    del self.pending_discoveries[pod_name]

    def _submit_async_task(self, coro, *args, **kwargs):
        """
        Submit an async coroutine to the event loop and return a Task object.

        Args:
            coro: The coroutine function to run
            *args, **kwargs: Arguments to pass to the coroutine

        Returns:
            An asyncio.Task object
        """
        return asyncio.run_coroutine_threadsafe(coro(*args, **kwargs), self.loop)

    def _watch_engines(self):
        # Main watch loop
        while self.running:
            try:
                for event in self.k8s_watcher.stream(
                    self.k8s_api.list_namespaced_pod,
                    namespace=self.namespace,
                    label_selector=self.label_selector,
                    timeout_seconds=30,
                ):
                    if not self.running:
                        break

                    pod = event["object"]
                    event_type = event["type"]
                    pod_name = pod.metadata.name
                    pod_ip = pod.status.pod_ip

                    # Skip malformed events
                    if not pod_name:
                        continue

                    is_pod_ready = self._check_pod_ready(pod.status.container_statuses)

                    # For DELETE events, handle immediately without async discovery
                    if event_type == "DELETED":
                        # Cancel any pending discovery for this pod
                        with self.pending_discoveries_lock:
                            if pod_name in self.pending_discoveries:
                                task = self.pending_discoveries.pop(pod_name)
                                task.cancel()

                        # Handle the deletion
                        with self.available_engines_lock:
                            self._on_engine_update(pod_name, pod_ip, event_type, is_pod_ready, None)
                        continue

                    # Limit concurrent discovery operations
                    with self.pending_discoveries_lock:
                        # Don't start new discoveries if we have too many pending
                        if len(self.pending_discoveries) > 10:
                            logger.warning(
                                f"Too many pending discoveries ({len(self.pending_discoveries)}), skipping {pod_name}"
                            )
                            continue

                        # For ADDED or MODIFIED events, only discover models if pod is ready and has an IP
                        if is_pod_ready and pod_ip:
                            # Cancel any existing pending discovery for this pod
                            if pod_name in self.pending_discoveries:
                                old_task = self.pending_discoveries.pop(pod_name)
                                old_task.cancel()

                            # Submit a new asynchronous discovery task to the event loop
                            task = self._submit_async_task(
                                self._async_discover_models, pod_name, pod_ip, event_type, is_pod_ready
                            )
                            self.pending_discoveries[pod_name] = task
                        else:
                            # Pod is not ready or has no IP, handle directly with no model names
                            with self.available_engines_lock:
                                self._on_engine_update(pod_name, pod_ip, event_type, is_pod_ready, None)

            except client.exceptions.ApiException as e:
                if e.status == 410:  # Resource version too old (Gone)
                    logger.warning(f"K8s watcher stream returned HTTP 410 (Gone): {e}. Restarting watch.")
                else:
                    logger.error(f"K8s watcher ApiException: {e}. Status: {e.status}, Reason: {e.reason}")
                time.sleep(1)  # Brief pause before restarting loop/watch
            except Exception as e:
                logger.error(f"K8s watcher error: {e}")
                time.sleep(1)  # Brief pause

    def _add_engine(self, engine_name: str, engine_ip: str, model_name: str):
        # engine_name is pod_name
        endpoint_key = (engine_name, model_name)
        logger.info(
            f"Adding/Updating serving endpoint for pod {engine_name} at {engine_ip}, running model: {model_name}"
        )
        self.available_engines[endpoint_key] = EndpointInfo(
            url=f"http://{engine_ip}:{self.port}",
            model_name=model_name,
            added_timestamp=int(time.time()),
        )

    def _delete_engine(self, engine_name: str):
        # engine_name is pod_name. This function removes all models associated with this pod.
        logger.info(
            f"Serving engine pod {engine_name} is being removed or is unhealthy. Removing all its associated model endpoints."
        )
        models_removed_count = 0
        keys_to_delete = [key for key in self.available_engines if key[0] == engine_name]
        if not keys_to_delete:
            logger.info(f"No model endpoints were registered for pod {engine_name} to remove.")
            return

        for key in keys_to_delete:
            if key in self.available_engines:
                del self.available_engines[key]
                models_removed_count += 1
                logger.debug(f"Deleted endpoint for model {key[1]} from pod {engine_name}")

        if models_removed_count > 0:
            logger.info(f"Removed {models_removed_count} model endpoint(s) associated with pod {engine_name}.")

    def _on_engine_update(
        self,
        engine_name: str,
        engine_ip: Optional[str],
        event: str,
        is_pod_ready: bool,
        model_names_reported: Optional[List[str]],
    ) -> None:
        # Note: This method should always be called with the available_engines_lock held
        if event == "ADDED":
            if engine_ip and is_pod_ready:
                if model_names_reported is not None:  # Check if _get_model_names succeeded
                    if model_names_reported:  # Ensure there are actual models
                        for mn in model_names_reported:
                            self._add_engine(engine_name, engine_ip, mn)
                    else:  # _get_model_names succeeded but returned an empty list
                        logger.info(f"Pod {engine_name} (ADDED) is ready and reported zero models.")
                else:  # _get_model_names failed (returned None)
                    logger.warning(f"Pod {engine_name} (ADDED) is ready but failed to retrieve model names.")
            # else: Pod not ready, no IP - do nothing for ADDED until it's ready and reports models.

        elif event == "DELETED":
            self._delete_engine(engine_name)  # Removes all models for this pod_name

        elif event == "MODIFIED":
            if not engine_ip:  # If IP is gone on MODIFIED, pod is likely unusable.
                logger.info(f"Pod {engine_name} (MODIFIED) has no IP. Removing associated model endpoints.")
                self._delete_engine(engine_name)
                return

            if is_pod_ready:
                # Pod is ready. model_names_reported could be:
                # - a list of model names (possibly empty if pod serves no models)
                # - None (if _get_model_names failed)

                current_registered_model_keys_for_pod = {
                    key for key in self.available_engines if key[0] == engine_name
                }
                current_registered_model_names_for_pod = {key[1] for key in current_registered_model_keys_for_pod}

                if model_names_reported is not None:  # _get_model_names succeeded
                    newly_reported_models_set = set(model_names_reported)

                    # Add/update models that are newly reported
                    for mn_new in newly_reported_models_set:
                        # _add_engine will update if (engine_name, mn_new) already exists, or add if new.
                        self._add_engine(engine_name, engine_ip, mn_new)

                    # Remove models that were registered but are no longer reported
                    models_to_remove = current_registered_model_names_for_pod - newly_reported_models_set
                    for mn_to_remove in models_to_remove:
                        endpoint_key_to_remove = (engine_name, mn_to_remove)
                        if endpoint_key_to_remove in self.available_engines:
                            del self.available_engines[endpoint_key_to_remove]
                            logger.info(
                                f"Removed model '{mn_to_remove}' from pod {engine_name} as it's no longer reported after MODIFIED event."
                            )

                    if not newly_reported_models_set and current_registered_model_names_for_pod:
                        logger.info(
                            f"Pod {engine_name} (MODIFIED) is ready but now reports zero models. All its previous models were removed."
                        )
                    elif not newly_reported_models_set:
                        logger.info(
                            f"Pod {engine_name} (MODIFIED) is ready and reported zero models (no changes to registration if it had none)."
                        )

                # If _get_model_names failed (returned None), we don't update anything to avoid removing working models
                # Just log the failure without modifying the registry
                elif model_names_reported is None:
                    logger.warning(
                        f"Pod {engine_name} (MODIFIED) is ready, but failed to retrieve model list. Keeping existing model registrations."
                    )
            else:  # Pod modified to be not ready
                logger.info(f"Pod {engine_name} (MODIFIED) is not ready. Removing all its associated model endpoints.")
                self._delete_engine(engine_name)

    def remove_endpoint_by_url(self, url: str) -> bool:
        """
        Remove an endpoint from the service discovery based on its URL.
        This is used for quick removal when a 500 error or connection error is detected.

        Args:
            url: The URL of the endpoint to remove

        Returns:
            True if any endpoints were removed, False otherwise
        """
        removed = False
        with self.available_engines_lock:
            # Find all engine keys (pod_name, model_name) for this URL
            keys_to_remove = []
            for key, endpoint_info in self.available_engines.items():
                if endpoint_info.url == url:
                    keys_to_remove.append(key)

            # Remove the found endpoints
            for key in keys_to_remove:
                del self.available_engines[key]
                logger.warning(f"Removed unhealthy endpoint for {key[1]} from {key[0]} with URL {url}")
                removed = True

        return removed

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
        # Cache health check results to avoid expensive checks on every call
        current_time = time.time()
        if current_time - self.last_health_check < self.health_check_interval:
            return self.last_health_status

        # Only perform health check periodically
        self.last_health_check = current_time

        # Primary health check - is the thread alive?
        if not self.watcher_thread.is_alive() or not self.event_loop_thread.is_alive():
            logger.error("Health check failed: Watcher thread or event loop thread is not alive")
            self.last_health_status = False
            return False

        # Check if we have too many pending discoveries (indicates a backup)
        with self.pending_discoveries_lock:
            pending_count = len(self.pending_discoveries)
            if pending_count > 20:
                logger.warning(f"Health check: High number of pending discoveries ({pending_count})")
                # Don't fail the health check just for having many pending discoveries
                # But log a warning to help with debugging

        # Check if we have any registered endpoints
        with self.available_engines_lock:
            if not self.available_engines:
                # Only log an error if we've been running for some time
                # to avoid false alarms during startup
                if current_time - self.last_health_check > 30:  # 30 seconds grace period
                    logger.warning("Health check: No available engines registered after 30 seconds")
                    # Don't fail health check during initial discovery phase

        # Everything looks good
        self.last_health_status = True
        return True

    def close(self):
        """
        Close the service discovery module.
        """
        self.running = False
        self.k8s_watcher.stop()

        # Cancel all pending async tasks
        logger.info("Cancelling pending async discovery tasks...")
        with self.pending_discoveries_lock:
            for task in self.pending_discoveries.values():
                task.cancel()
            self.pending_discoveries.clear()

        # Close the aiohttp session
        if hasattr(self, "session"):
            close_session_future = asyncio.run_coroutine_threadsafe(self.session.close(), self.loop)
            try:
                close_session_future.result(timeout=5)
                logger.info("aiohttp session closed")
            except Exception as e:
                logger.warning(f"Error closing aiohttp session: {e}")

        # Stop the event loop
        self.loop.call_soon_threadsafe(self.loop.stop)
        logger.info("Stopped async event loop")

        # Wait for threads to finish
        self.watcher_thread.join(timeout=5)
        self.event_loop_thread.join(timeout=5)
        logger.info("All threads terminated")


def _create_service_discovery(service_discovery_type: ServiceDiscoveryType, *args, **kwargs) -> ServiceDiscovery:
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
        return K8sServiceDiscovery(*args, **kwargs)
    else:
        raise ValueError("Invalid service discovery type")


def initialize_service_discovery(service_discovery_type: ServiceDiscoveryType, *args, **kwargs) -> ServiceDiscovery:
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

    _global_service_discovery = _create_service_discovery(service_discovery_type, *args, **kwargs)
    return _global_service_discovery


def reconfigure_service_discovery(service_discovery_type: ServiceDiscoveryType, *args, **kwargs) -> ServiceDiscovery:
    """
    Reconfigure the service discovery module with the given type and arguments.
    """
    global _global_service_discovery
    if _global_service_discovery is None:
        raise ValueError("Service discovery module not initialized")

    new_service_discovery = _create_service_discovery(service_discovery_type, *args, **kwargs)

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
