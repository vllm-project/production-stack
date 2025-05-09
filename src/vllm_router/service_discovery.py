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
        return [
            EndpointInfo(url, model, self.added_timestamp)
            for url, model in zip(self.urls, self.models)
        ]


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
        self.session = aiohttp.ClientSession()
        
    def _run_event_loop(self):
        """Run the asyncio event loop in a separate thread"""
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_forever()
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
            # Use aiohttp for async HTTP requests with timeout
            timeout = aiohttp.ClientTimeout(total=10)
            async with self.session.get(url, headers=headers, timeout=timeout) as response:
                response.raise_for_status()
                data = (await response.json()).get("data")

                if isinstance(data, list):
                    for model_entry in data:
                        if isinstance(model_entry, dict) and "id" in model_entry and model_entry["id"]:
                            model_names_list.append(model_entry["id"])
                
                if not model_names_list: # This means data was not a list, was empty, or contained no valid model_entries
                    logger.warning(f"No model IDs found or 'data' was not a list/empty in response from {url}. Response status: {response.status}")
                    # If the API successfully returns an empty list of models, we should return an empty list.
                    # If there was an issue with the 'data' field itself not being a list, or structure is wrong, then None is more appropriate.
                    if data is None or not isinstance(data, list):
                        logger.error(f"Field 'data' missing or not a list in response from {url}")
                        return None # Indicates an issue with the response structure beyond just an empty list of models
                    # If data is an empty list, model_names_list will be empty, and that's what will be returned.

        except asyncio.TimeoutError:
            logger.error(f"Timeout when getting model names from {url}")
            return None
        except aiohttp.ClientError as e: # Covers ConnectionError, HTTPError, etc.
            logger.error(f"Request failed to get model names from {url}: {e}")
            return None
        except (ValueError, KeyError) as e: # Handles JSON parsing errors or missing keys like "data" or "id"
            logger.error(f"Failed to parse model names from response of {url}: {e}")
            return None
        except Exception as e: # Catch-all for other unexpected errors
            logger.error(f"Unexpected error when getting model names from {url}: {e}")
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
            self._on_engine_update(pod_name, pod_ip, event_type, is_pod_ready, model_names_reported)
            
        except Exception as e:
            logger.error(f"Error in async model discovery for pod {pod_name}: {str(e)}")
            # Still call _on_engine_update with model_names_reported=None to handle the error case
            self._on_engine_update(pod_name, pod_ip, event_type, is_pod_ready, None)
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
        # TODO (ApostaC): remove the hard-coded timeouts

        while self.running:
            try:
                for event in self.k8s_watcher.stream(
                    self.k8s_api.list_namespaced_pod,
                    namespace=self.namespace,
                    label_selector=self.label_selector,
                    timeout_seconds=30, # This is watcher stream timeout, not request timeout
                ):
                    pod = event["object"]
                    event_type = event["type"]
                    pod_name = pod.metadata.name
                    pod_ip = pod.status.pod_ip # pod_ip can be None if pod is not fully up
                    
                    is_pod_ready = self._check_pod_ready(pod.status.container_statuses)
                    
                    # For DELETE events, handle immediately without async discovery
                    if event_type == "DELETED":
                        # Cancel any pending discovery for this pod
                        with self.pending_discoveries_lock:
                            if pod_name in self.pending_discoveries:
                                task = self.pending_discoveries.pop(pod_name)
                                task.cancel()
                        
                        # Handle the deletion
                        self._on_engine_update(pod_name, pod_ip, event_type, is_pod_ready, None)
                        continue
                    
                    # For ADDED or MODIFIED events, only discover models if pod is ready and has an IP
                    if is_pod_ready and pod_ip:
                        # Cancel any existing pending discovery for this pod
                        with self.pending_discoveries_lock:
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
                        self._on_engine_update(pod_name, pod_ip, event_type, is_pod_ready, None)

            except client.exceptions.ApiException as e:
                if e.status == 410: # Resource version too old (Gone)
                    logger.warning(f"K8s watcher stream returned HTTP 410 (Gone): {e}. Restarting watch.")
                else:
                    logger.error(f"K8s watcher ApiException: {e}. Status: {e.status}, Reason: {e.reason}")
                time.sleep(1) # Brief pause before restarting loop/watch
            except Exception as e:
                logger.error(f"K8s watcher error: {e}")
                time.sleep(1) # Brief pause

    def _add_engine(self, engine_name: str, engine_ip: str, model_name: str):
        # engine_name is pod_name
        endpoint_key = (engine_name, model_name)
        logger.info(
            f"Adding/Updating serving endpoint for pod {engine_name} at "
            f"{engine_ip}, running model: {model_name}"
        )
        with self.available_engines_lock:
            self.available_engines[endpoint_key] = EndpointInfo(
                url=f"http://{engine_ip}:{self.port}",
                model_name=model_name,
                added_timestamp=int(time.time()),
            )

    def _delete_engine(self, engine_name: str):
        # engine_name is pod_name. This function removes all models associated with this pod.
        logger.info(f"Serving engine pod {engine_name} is being removed or is unhealthy. Removing all its associated model endpoints.")
        models_removed_count = 0
        with self.available_engines_lock:
            keys_to_delete = [
                key for key in self.available_engines if key[0] == engine_name
            ]
            if not keys_to_delete:
                 logger.info(f"No model endpoints were registered for pod {engine_name} to remove.")
                 return

            for key in keys_to_delete:
                # Check if key still exists, as another thread might have modified it, though less likely with this design.
                if key in self.available_engines:
                    del self.available_engines[key]
                    models_removed_count += 1
                    logger.debug(f"Deleted endpoint for model {key[1]} from pod {engine_name}")
        if models_removed_count > 0:
            logger.info(f"Removed {models_removed_count} model endpoint(s) associated with pod {engine_name}.")
        

    def _on_engine_update(
        self,
        engine_name: str, # This is pod_name
        engine_ip: Optional[str],
        event: str,
        is_pod_ready: bool,
        model_names_reported: Optional[List[str]], # List of model names, or None if _get_model_names failed
    ) -> None:
        if event == "ADDED":
            if engine_ip and is_pod_ready:
                if model_names_reported is not None: # Check if _get_model_names succeeded
                    if model_names_reported: # Ensure there are actual models
                        for mn in model_names_reported:
                            self._add_engine(engine_name, engine_ip, mn)
                    else: # _get_model_names succeeded but returned an empty list
                        logger.info(f"Pod {engine_name} (ADDED) is ready and reported zero models.")
                else: # _get_model_names failed (returned None)
                    logger.warning(f"Pod {engine_name} (ADDED) is ready but failed to retrieve model names.")
            # else: Pod not ready, no IP - do nothing for ADDED until it's ready and reports models.

        elif event == "DELETED":
            self._delete_engine(engine_name) # Removes all models for this pod_name

        elif event == "MODIFIED":
            if not engine_ip: # If IP is gone on MODIFIED, pod is likely unusable.
                logger.info(f"Pod {engine_name} (MODIFIED) has no IP. Removing associated model endpoints.")
                self._delete_engine(engine_name)
                return

            if is_pod_ready:
                # Pod is ready. model_names_reported could be:
                # - a list of model names (possibly empty if pod serves no models)
                # - None (if _get_model_names failed)
                
                with self.available_engines_lock:
                    current_registered_model_keys_for_pod = {
                        key for key in self.available_engines if key[0] == engine_name
                    }
                    current_registered_model_names_for_pod = {key[1] for key in current_registered_model_keys_for_pod}
                    
                    if model_names_reported is not None: # _get_model_names succeeded
                        newly_reported_models_set = set(model_names_reported)

                        # Add/update models that are newly reported
                        for mn_new in newly_reported_models_set:
                            # _add_engine will update if (engine_name, mn_new) already exists, or add if new.
                            self._add_engine(engine_name, engine_ip, mn_new)
                        
                        # Remove models that were registered but are no longer reported
                        models_to_remove = current_registered_model_names_for_pod - newly_reported_models_set
                        for mn_to_remove in models_to_remove:
                            endpoint_key_to_remove = (engine_name, mn_to_remove)
                            if endpoint_key_to_remove in self.available_engines: # Should always be true
                                del self.available_engines[endpoint_key_to_remove]
                                logger.info(f"Removed model '{mn_to_remove}' from pod {engine_name} as it's no longer reported after MODIFIED event.")
                        
                        if not newly_reported_models_set and current_registered_model_names_for_pod:
                            logger.info(f"Pod {engine_name} (MODIFIED) is ready but now reports zero models. All its previous models were removed.")
                        elif not newly_reported_models_set:
                             logger.info(f"Pod {engine_name} (MODIFIED) is ready and reported zero models (no changes to registration if it had none).")

                    else: # _get_model_names failed (returned None)
                        # Pod is ready, but we couldn't get its models.
                        # This is a tricky state. We should probably remove existing models for this pod,
                        # as we can't confirm they are still valid.
                        logger.warning(f"Pod {engine_name} (MODIFIED) is ready, but failed to retrieve model list. Removing all previously registered models for this pod.")
                        self._delete_engine(engine_name) # Treat as if it's unhealthy from a model reporting perspective

            else: # Pod modified to be not ready
                logger.info(f"Pod {engine_name} (MODIFIED) is not ready. Removing all its associated model endpoints.")
                self._delete_engine(engine_name)

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
        # Cancel all pending async tasks
        logger.info("Cancelling pending async discovery tasks...")
        with self.pending_discoveries_lock:
            for task in self.pending_discoveries.values():
                task.cancel()
            self.pending_discoveries.clear()
        
        # Close the aiohttp session
        if hasattr(self, 'session'):
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
        return K8sServiceDiscovery(*args, **kwargs)
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
