from unittest.mock import MagicMock, patch
import pytest
import time

from vllm_router.service_discovery import K8sPodIPServiceDiscovery, EndpointInfo


@pytest.fixture
def mock_app():
    """Mock FastAPI app instance."""
    app = MagicMock()
    app.state = MagicMock()
    return app


@pytest.fixture
def mock_k8s_dependencies():
    """Mock all Kubernetes dependencies."""
    with (
        patch("vllm_router.service_discovery.config") as mock_config,
        patch("vllm_router.service_discovery.client.CoreV1Api") as mock_api_class,
        patch("vllm_router.service_discovery.watch.Watch") as mock_watch_class,
        patch("vllm_router.service_discovery.requests") as mock_requests,
    ):
        # Mock config loading
        mock_config.load_incluster_config.return_value = None

        # Mock API client
        mock_api = MagicMock()
        mock_api_class.return_value = mock_api

        # Mock watcher
        mock_watcher = MagicMock()
        mock_watch_class.return_value = mock_watcher

        # Mock HTTP responses
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": [{"id": "test-model"}]}
        mock_response.raise_for_status.return_value = None
        mock_requests.get.return_value = mock_response

        yield {
            "config": mock_config,
            "api": mock_api,
            "watcher": mock_watcher,
            "requests": mock_requests,
        }


def create_mock_pod_event(
    event_type,
    pod_name,
    pod_ip,
    ready=True,
    terminating=False,
    model_label="test-model",
):
    """Helper method to create a mock Kubernetes pod event."""
    pod = MagicMock()
    pod.metadata.name = pod_name
    pod.metadata.labels = {"model": model_label} if model_label else {}
    if terminating:
        pod.metadata.deletion_timestamp = "2024-01-01T00:00:00Z"
    else:
        pod.metadata.deletion_timestamp = None

    pod.status.pod_ip = pod_ip
    pod.status.container_statuses = [MagicMock(ready=ready)] if ready else []

    return {"type": event_type, "object": pod}


def test_scenario_1_two_pods_present(mock_app, mock_k8s_dependencies):
    """Test scenario 1: 2 model pods present and running."""

    # Create a generator that yields events and then stops
    def mock_stream_generator():
        yield create_mock_pod_event(
            "ADDED", "engine_1", "10.0.0.1", ready=True, model_label="model-1"
        )
        yield create_mock_pod_event(
            "ADDED", "engine_2", "10.0.0.2", ready=True, model_label="model-2"
        )
        # Stop after yielding the events
        raise Exception("Simulated timeout")

    mock_k8s_dependencies["watcher"].stream.return_value = mock_stream_generator()

    # Mock sleep mode check to return False
    with patch.object(
        K8sPodIPServiceDiscovery, "_check_engine_sleep_mode", return_value=False
    ):
        discovery = K8sPodIPServiceDiscovery(
            app=mock_app, namespace="test-namespace", port="8000"
        )

        # Give the watcher thread time to process the events
        time.sleep(
            0.1
        )  # hardcoded 0.1 so that while the watcher sleeps after failing, this sleeping is exhausted

        # Check that both engines are in available_engines
        assert len(discovery.available_engines) == 2
        assert "engine_1" in discovery.available_engines
        assert "engine_2" in discovery.available_engines

        # Verify the endpoint info
        engine_1 = discovery.available_engines["engine_1"]
        engine_2 = discovery.available_engines["engine_2"]

        assert isinstance(engine_1, EndpointInfo)
        assert isinstance(engine_2, EndpointInfo)
        assert engine_1.url == "http://10.0.0.1:8000"
        assert engine_2.url == "http://10.0.0.2:8000"
        assert engine_1.model_names == ["test-model"]
        assert engine_2.model_names == ["test-model"]
        assert engine_1.model_label == "model-1"
        assert engine_2.model_label == "model-2"

        discovery.close()


def test_scenario_2_pod_deletion(mock_app, mock_k8s_dependencies):
    """Test scenario 2: 2 pods present, then 1 gets deleted."""

    # Mock the watcher stream to return 2 ADDED events followed by 1 DELETED event
    # Create a generator that yields events and then stops
    def mock_stream_generator():
        yield create_mock_pod_event(
            "ADDED", "engine_1", "10.0.0.1", ready=True, model_label="model-1"
        )
        yield create_mock_pod_event(
            "ADDED", "engine_2", "10.0.0.2", ready=True, model_label="model-2"
        )
        yield create_mock_pod_event(
            "DELETED", "engine_1", "10.0.0.1", ready=True, model_label="model-1"
        )
        # Stop after yielding the events
        raise Exception("Simulated timeout")

    mock_k8s_dependencies["watcher"].stream.return_value = mock_stream_generator()

    # Mock sleep mode check to return False
    with patch.object(
        K8sPodIPServiceDiscovery, "_check_engine_sleep_mode", return_value=False
    ):
        discovery = K8sPodIPServiceDiscovery(
            app=mock_app, namespace="test-namespace", port="8000"
        )

        # Give the watcher thread time to process all events
        time.sleep(0.3)

        # Check that only engine_2 remains in available_engines
        assert len(discovery.available_engines) == 1
        assert "engine_1" not in discovery.available_engines
        assert "engine_2" in discovery.available_engines

        # Verify the remaining endpoint info
        engine_2 = discovery.available_engines["engine_2"]
        assert isinstance(engine_2, EndpointInfo)
        assert engine_2.url == "http://10.0.0.2:8000"
        assert engine_2.model_names == ["test-model"]
        assert engine_2.model_label == "model-2"

        discovery.close()


def test_scenario_3_pod_addition_after_timeout(mock_app, mock_k8s_dependencies, caplog):
    """Test scenario 3: 2 pods present, then 1 more added after timeout."""

    # Create a generator that yields different events on each iteration
    def mock_stream_generator():
        # First iteration: 2 pods
        yield create_mock_pod_event(
            "ADDED", "engine_1", "10.0.0.1", ready=True, model_label="model-1"
        )
        yield create_mock_pod_event(
            "ADDED", "engine_2", "10.0.0.2", ready=True, model_label="model-2"
        )

        # Simulate timeout by raising StopIteration
        raise StopIteration()

    def mock_stream_generator_second():
        # Second iteration: 3 pods (including the new one)
        yield create_mock_pod_event(
            "ADDED", "engine_1", "10.0.0.1", ready=True, model_label="model-1"
        )
        yield create_mock_pod_event(
            "ADDED", "engine_2", "10.0.0.2", ready=True, model_label="model-2"
        )
        yield create_mock_pod_event(
            "ADDED", "engine_3", "10.0.0.3", ready=True, model_label="model-3"
        )

        # Simulate timeout
        raise StopIteration()

    # Mock the watcher stream to use our generator
    mock_k8s_dependencies["watcher"].stream.side_effect = [
        mock_stream_generator(),
        mock_stream_generator_second(),
    ]

    # Mock sleep mode check to return False
    with patch.object(
        K8sPodIPServiceDiscovery, "_check_engine_sleep_mode", return_value=False
    ):
        discovery = K8sPodIPServiceDiscovery(
            app=mock_app, namespace="test-namespace", port="8000"
        )

        # Give the watcher thread time to process the first iteration
        time.sleep(0.5)
        discovery.running = False  # Stop the while loop

        # Check that both engines are in available_engines after first iteration
        assert len(discovery.available_engines) == 2
        assert "engine_1" in discovery.available_engines
        assert "engine_2" in discovery.available_engines
        assert "engine_3" not in discovery.available_engines
        discovery.running = True  # Restart the while loop

        # Give more time for the second iteration to process
        time.sleep(0.5)

        # Check that all three engines are in available_engines after second iteration
        assert len(discovery.available_engines) == 3
        assert "engine_1" in discovery.available_engines
        assert "engine_2" in discovery.available_engines
        assert "engine_3" in discovery.available_engines

        # Verify the new endpoint info
        engine_3 = discovery.available_engines["engine_3"]
        assert isinstance(engine_3, EndpointInfo)
        assert engine_3.url == "http://10.0.0.3:8000"
        assert engine_3.model_names == ["test-model"]
        assert engine_3.model_label == "model-3"

        discovery.close()


def test_scenario_4_slow_models_call_blocks_deletion(mock_app, mock_k8s_dependencies):
    """Test scenario 4: Slow /v1/models call blocks deletion event processing."""

    # Track how many times we've been called to simulate different behaviors
    should_call_false = False

    def mock_slow_requests_get(url, headers=None):
        if should_call_false:
            # Third call to engine_1's /v1/models - simulate slow response
            time.sleep(
                40
            )  # Simulate a slow call that would exceed timeout in real scenario
            raise Exception("Simulated slow response")
        else:
            # Normal fast response for other calls
            mock_response = MagicMock()
            mock_response.json.return_value = {"data": [{"id": "test-model"}]}
            mock_response.raise_for_status.return_value = None
            return mock_response

    # Create generators for each watch iteration
    def mock_stream_generator_first():
        # First iteration: 2 pods added
        yield create_mock_pod_event(
            "ADDED", "engine_1", "10.0.0.1", ready=True, model_label="model-1"
        )
        yield create_mock_pod_event(
            "ADDED", "engine_2", "10.0.0.2", ready=True, model_label="model-2"
        )
        raise Exception("Simulated timeout")

    def mock_stream_generator_second():
        # Second iteration: same 2 pods added again (no change)
        yield create_mock_pod_event(
            "ADDED", "engine_1", "10.0.0.1", ready=True, model_label="model-1"
        )
        yield create_mock_pod_event(
            "ADDED", "engine_2", "10.0.0.2", ready=True, model_label="model-2"
        )
        raise Exception("Simulated timeout")

    def mock_stream_generator_third():
        # Third iteration: engine_1 slow call, engine_2 deleted
        yield create_mock_pod_event(
            "ADDED", "engine_1", "10.0.0.1", ready=True, model_label="model-1"
        )
        yield create_mock_pod_event(
            "DELETED", "engine_2", "10.0.0.2", ready=True, model_label="model-2"
        )
        raise Exception("Simulated timeout")

    # Mock the watcher stream to use our generators
    mock_k8s_dependencies["watcher"].stream.side_effect = [
        mock_stream_generator_first(),
        mock_stream_generator_second(),
        mock_stream_generator_third(),
    ]

    # Mock the requests.get to simulate slow response
    mock_k8s_dependencies["requests"].get.side_effect = mock_slow_requests_get

    # Mock sleep mode check to return False
    with patch.object(
        K8sPodIPServiceDiscovery, "_check_engine_sleep_mode", return_value=False
    ):
        discovery = K8sPodIPServiceDiscovery(
            app=mock_app, namespace="test-namespace", port="8000"
        )

        # First iteration: Give time for both engines to be added
        time.sleep(0.5)
        discovery.running = False

        # Check that both engines are in available_engines after first iteration
        assert len(discovery.available_engines) == 2
        assert "engine_1" in discovery.available_engines
        assert "engine_2" in discovery.available_engines
        discovery.running = True

        # Second iteration: Give time for the second iteration (should be no change)
        time.sleep(0.5)
        discovery.running = False

        # Check that both engines are still in available_engines after second iteration
        assert len(discovery.available_engines) == 2
        assert "engine_1" in discovery.available_engines
        assert "engine_2" in discovery.available_engines
        should_call_false = True
        discovery.running = True

        # Third iteration: Give time for the third iteration
        # The slow call to engine_1's /v1/models should block processing
        # and prevent the DELETED event for engine_2 from being processed
        time.sleep(0.5)
        discovery.running = False

        # Check that engine_2 is still in available_engines because the DELETED event
        # was not processed due to the slow /v1/models call blocking the stream
        assert len(discovery.available_engines) == 2
        assert "engine_1" in discovery.available_engines
        assert "engine_2" in discovery.available_engines  # Should still be here!

        # Verify that engine_1 is still there (even though the /v1/models call was slow)
        engine_1 = discovery.available_engines["engine_1"]
        engine_2 = discovery.available_engines["engine_2"]

        assert isinstance(engine_1, EndpointInfo)
        assert isinstance(engine_2, EndpointInfo)
        assert engine_1.url == "http://10.0.0.1:8000"
        assert engine_2.url == "http://10.0.0.2:8000"

        discovery.close()
