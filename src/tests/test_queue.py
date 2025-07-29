import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch
from vllm_router.services.queue_service.queue import (
    initialize_queue_manager,
    get_queue_manager,
)
from fastapi.responses import StreamingResponse
import pytest_asyncio


@pytest.fixture
def mock_scraper():
    scraper = MagicMock()
    scraper.get_engine_stats.return_value = {
        "endpoint1": MagicMock(num_running_requests=0, gpu_cache_usage_perc=0),
        "endpoint2": MagicMock(num_running_requests=5, gpu_cache_usage_perc=50),
    }
    return scraper


@pytest_asyncio.fixture
async def queue_manager(mock_scraper):
    initialize_queue_manager(
        max_queue_wait_time=10,
        max_running_requests=10,
        max_gpu_perc=95,
        scraper=mock_scraper
    )
    manager = get_queue_manager()
    await manager.register_endpoint("endpoint1")
    await manager.register_endpoint("endpoint2")
    yield manager
    await manager.close()


@pytest.mark.asyncio
async def test_queue_manager_initialization(mock_scraper):
    initialize_queue_manager(
        max_queue_wait_time=10,
        max_running_requests=10,
        max_gpu_perc=95,
        scraper=mock_scraper
    )
    manager = get_queue_manager()
    assert manager.max_queue_wait_time == 10
    assert manager.max_running_requests == 10
    assert manager.max_gpu_perc == 95
    assert manager.scraper == mock_scraper


@pytest.mark.asyncio
async def test_register_endpoint(queue_manager):
    # Already registered by fixture; just test existence
    for endpoint in ["endpoint1", "endpoint2"]:
        assert endpoint in queue_manager.endpoint_queues
        assert endpoint in queue_manager.conditions
        assert endpoint in queue_manager.endpoint_tasks


@pytest.mark.asyncio
async def test_enqueue_request(queue_manager):
    test_request = {"request_id": "test123", "body": "test"}
    future = asyncio.Future()
    await queue_manager.enqueue("endpoint1", test_request, priority=1, result_future=future)
    assert queue_manager.endpoint_queues["endpoint1"]._queue
    assert not future.done()


@pytest.mark.asyncio
async def test_endpoint_is_free(queue_manager, mock_scraper):
    assert queue_manager._endpoint_is_free("endpoint1") is True
    assert queue_manager._endpoint_is_free("endpoint2") is True

    mock_scraper.get_engine_stats.return_value["endpoint2"].num_running_requests = 15
    assert queue_manager._endpoint_is_free("endpoint2") is False

    mock_scraper.get_engine_stats.return_value["endpoint2"].num_running_requests = 5
    mock_scraper.get_engine_stats.return_value["endpoint2"].gpu_cache_usage_perc = 96
    assert queue_manager._endpoint_is_free("endpoint2") is False


@pytest.mark.asyncio
async def test_dispatch_and_signal(queue_manager):
    test_request = {
        "request_id": "test123",
        "body": "test",
        "request": MagicMock(),
        "endpoint": "endpoint1",
        "background_tasks": MagicMock(),
        "_result_future": asyncio.Future()
    }

    mock_response = StreamingResponse(content=MagicMock())

    with patch("vllm_router.services.request_service.request.process_request", new_callable=AsyncMock) as mock_process:
        # Simulate response async generator
        async def mock_stream():
            yield ({"content-type": "application/json"}, 200)
            yield StreamingResponse(content=MagicMock())

        mock_process.return_value = mock_stream()
        await queue_manager._dispatch_and_signal("endpoint1", test_request)

        assert test_request["_result_future"].done()
        assert isinstance(test_request["_result_future"].result(), StreamingResponse)


@pytest.mark.asyncio
async def test_scheduler_loop(queue_manager):
    test_request = {
    "request_id": "test123",
    "body": "test",
    "request": MagicMock(),  # ← Required by `process_request(...)`
    "endpoint": "endpoint1",  # ← Required
    "background_tasks": MagicMock(),
    "_result_future": asyncio.Future()
    }

    await queue_manager.enqueue("endpoint1", test_request)
    await asyncio.sleep(1)
    assert not queue_manager.endpoint_queues["endpoint1"]._queue
    assert test_request["_result_future"].done()


@pytest.mark.asyncio
async def test_stale_request_rerouting(queue_manager):
    stale_request = {
        "request_id": "stale123",
        "body": "test",
        "_result_future": asyncio.Future(),
        "enqueue_time": time.time() - 20
    }

    with patch.object(queue_manager, "_reroute_or_dispatch_stale_request", new_callable=AsyncMock) as mock_reroute:
        await queue_manager.enqueue("endpoint1", stale_request)
        for _ in range(10):
            if mock_reroute.call_count:
                break
            await asyncio.sleep(0.1)
        mock_reroute.assert_called_once()

        mock_reroute.assert_called_once()


@pytest.mark.asyncio
async def test_shutdown(queue_manager):
    assert not queue_manager._shutdown_event.is_set()
    await queue_manager.close()
    assert queue_manager._shutdown_event.is_set()
    for task in queue_manager.endpoint_tasks.values():
        assert task.done()


@pytest.mark.asyncio
async def test_singleton_pattern():
    from vllm_router.services.queue_service import queue as queue_module

    queue_module._global_queue_manager = None  # Reset locally

    scraper = MagicMock()
    scraper.get_engine_stats.return_value = {
        "endpoint1": MagicMock(num_running_requests=0, gpu_cache_usage_perc=0),
    }

    queue_module.initialize_queue_manager(
        max_queue_wait_time=10,
        max_running_requests=10,
        max_gpu_perc=95,
        scraper=scraper
    )
    manager1 = queue_module.get_queue_manager()
    manager2 = queue_module.get_queue_manager()
    assert manager1 is manager2

    await manager1.close()
    queue_module._global_queue_manager = None

    with pytest.raises(ValueError, match="Queue manager not initialized"):
        queue_module.get_queue_manager()
