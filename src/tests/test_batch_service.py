import os

import pytest

from vllm_router.services.batch_service import initialize_batch_processor
from vllm_router.services.batch_service.batch import BatchStatus
from vllm_router.services.files_service.file_storage import FileStorage

pytest_plugins = ("pytest_asyncio",)


@pytest.fixture
def processor(tmp_path):
    storage = FileStorage(os.path.join(tmp_path, "files"))
    return initialize_batch_processor("local", os.path.join(tmp_path, "db"), storage)


def test_initialize_local_batch_processor(processor):
    """app.py calls this whenever --enable-batch-api is passed, so an import
    error inside local_processor aborts router startup."""
    assert processor.db_path.endswith("batch_queue.db")


@pytest.mark.asyncio
async def test_create_and_retrieve_batch(processor):
    await processor.setup_db()

    created = await processor.create_batch(
        input_file_id="file-1",
        endpoint="/v1/chat/completions",
        completion_window="24h",
    )
    retrieved = await processor.retrieve_batch(created.id)

    assert retrieved.id == created.id
    assert retrieved.status is BatchStatus.PENDING
    assert retrieved.input_file_id == "file-1"
