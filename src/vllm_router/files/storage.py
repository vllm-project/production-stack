from abc import ABC, abstractmethod
from typing import List

from vllm_router.files.files import OpenAIFile


class Storage(ABC):
    """
    Abstract class for file storage.

    The storage should be able to save, retrieve, and delete files.
    It is used to support file uploads and downloads for batch inference.
    """

    DEFAULT_USER_ID = "uid_default"
    DEFAULT_PURPOSE = "batch"

    @abstractmethod
    async def save_file(
        self,
        file_id: str = None,
        user_id: str = DEFAULT_USER_ID,
        file_name: str = None,
        content: bytes = None,
        purpose: str = DEFAULT_PURPOSE,
    ) -> OpenAIFile:
        pass

    @abstractmethod
    async def save_file_chunk(
        self,
        file_id: str,
        user_id: str = DEFAULT_USER_ID,
        chunk: bytes = None,
        purpose: str = DEFAULT_PURPOSE,
        offset: int = 0,
    ) -> None:
        pass

    async def get_file(
        self, file_id: str, user_id: str = DEFAULT_USER_ID
    ) -> OpenAIFile:
        pass

    @abstractmethod
    async def get_file_content(
        self, file_id: str, user_id: str = DEFAULT_USER_ID
    ) -> bytes:
        pass

    @abstractmethod
    async def list_files(self, user_id: str = DEFAULT_USER_ID) -> List[str]:
        pass

    @abstractmethod
    async def delete_file(self, file_id: str, user_id: str = DEFAULT_USER_ID):
        pass


def initialize_storage(storage_type: str, base_path: str = None) -> Storage:
    if storage_type == "local_file":
        from vllm_router.files.file_storage import FileStorage

        return FileStorage(base_path)
    else:
        raise ValueError(f"Unsupported storage type: {storage_type}")
