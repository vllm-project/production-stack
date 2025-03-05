import asyncio
import os
import shutil

import pytest

from vllm_router.services.files_service.file_storage import FileStorage
from vllm_router.services.files_service.openai_files import OpenAIFile

TEST_BASE_PATH = "/tmp/test_vllm_files"
pytest_plugins = ("pytest_asyncio",)


@pytest.fixture(autouse=True)
async def cleanup():
    """Cleanup test files after each test"""
    print("Cleaning up test files")
    if os.path.exists(TEST_BASE_PATH):
        await asyncio.to_thread(shutil.rmtree, TEST_BASE_PATH)
    yield
    print("Cleaning up test files")
    if os.path.exists(TEST_BASE_PATH):
        await asyncio.to_thread(shutil.rmtree, TEST_BASE_PATH)


@pytest.fixture
def storage():
    """Create a FileStorage instance for testing"""
    return FileStorage(TEST_BASE_PATH)


@pytest.mark.asyncio
async def test_save_and_get_file(storage):
    """Test basic file save and retrieval operations"""
    test_content = b"Hello, World!"
    test_filename = "test.txt"

    # Save file
    saved_file = await storage.save_file(
        file_name=test_filename, content=test_content, purpose="test"
    )

    assert isinstance(saved_file, OpenAIFile)
    assert saved_file.filename == test_filename
    assert saved_file.bytes == len(test_content)
    assert saved_file.purpose == "test"

    # Get file metadata
    retrieved_file = await storage.get_file(saved_file.id)
    assert isinstance(retrieved_file, OpenAIFile)
    assert retrieved_file.id == saved_file.id
    # File name is not stored in metadata yet.
    # assert retrieved_file.filename == test_filename
    assert retrieved_file.bytes == len(test_content)

    # Get file content
    content = await storage.get_file_content(saved_file.id)
    assert content == test_content


@pytest.mark.asyncio
async def test_list_files(storage):
    """Test listing files"""
    # I am not sure why this is necessary. The cleanup fixture should
    # take care of this. But the test fails without this line.
    shutil.rmtree(TEST_BASE_PATH)

    # Save multiple files
    files = []
    for i in range(3):
        file = await storage.save_file(
            file_name=f"test{i}.txt",
            content=f"content{i}".encode(),
        )
        files.append(file)

    # List files
    file_list = await storage.list_files()
    assert len(file_list) == 3
    for file in files:
        assert file.id in file_list


@pytest.mark.asyncio
async def test_delete_file(storage):
    """Test file deletion"""
    # Save a file
    saved_file = await storage.save_file(
        file_name="test.txt",
        content=b"test content",
    )

    # Verify file exists
    files = await storage.list_files()
    assert saved_file.id in files

    # Delete file
    await storage.delete_file(saved_file.id)

    # Verify file is deleted
    files = await storage.list_files()
    assert saved_file.id not in files

    # Try to get deleted file
    with pytest.raises(FileNotFoundError):
        await storage.get_file(saved_file.id)


@pytest.mark.asyncio
async def test_save_file_with_explicit_id(storage):
    """Test saving a file with an explicit ID"""
    explicit_id = "custom-id-123"
    content = b"test content"

    saved_file = await storage.save_file(
        file_id=explicit_id,
        file_name="test.txt",
        content=content,
    )

    assert saved_file.id == explicit_id
    retrieved_content = await storage.get_file_content(explicit_id)
    assert retrieved_content == content


# TODO(gaocegege): Add test for saving file chunk


@pytest.mark.asyncio
async def test_error_conditions(storage):
    """Test various error conditions"""
    # Test saving file with no content
    with pytest.raises(ValueError):
        await storage.save_file(file_name="test.txt")

    # Test getting non-existent file
    with pytest.raises(FileNotFoundError):
        await storage.get_file("nonexistent-file")

    # Test getting content of non-existent file
    with pytest.raises(FileNotFoundError):
        await storage.get_file_content("nonexistent-file")
