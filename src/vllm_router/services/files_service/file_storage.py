import os
import uuid
from typing import List

import aiofiles

from vllm_router.log import init_logger
from vllm_router.services.files_service.openai_files import OpenAIFile
from vllm_router.services.files_service.storage import Storage

logger = init_logger(__name__)


class FileStorage(Storage):
    """
    File storage implementation using the local filesystem.

    Files are stored in the following directory structure:
    /tmp/vllm_files/<user_id>/<file_id>

    user_id is not used in the current implementation. It is reserved for future use.
    """

    def __init__(self, base_path: str = "/tmp/vllm_files"):
        self.base_path = base_path
        logger.info("Initialize FileStorage with base path %s", base_path)
        os.makedirs(base_path, exist_ok=True)

    def _get_user_path(self, user_id: str) -> str:
        """Get user-specific directory path"""
        user_path = os.path.join(self.base_path, user_id)
        os.makedirs(user_path, exist_ok=True)
        return user_path

    async def save_file(
        self,
        file_id: str = None,
        user_id: str = Storage.DEFAULT_USER_ID,
        file_name: str = None,
        content: bytes = None,
        purpose: str = Storage.DEFAULT_PURPOSE,
    ) -> OpenAIFile:
        """Save file content to disk"""
        if content is None:
            raise ValueError("Content cannot be None")
        if file_id is None:
            file_id = f"file-{uuid.uuid4().hex[:6]}"

        # Save file to disk. File name is the same as file_id.
        user_path = self._get_user_path(user_id)
        file_path = os.path.join(user_path, file_id)
        async with aiofiles.open(file_path, "wb") as f:
            await f.write(content)

        # Create OpenAIFile object.
        file_size = len(content)
        created_at = int(os.path.getctime(file_path))
        return OpenAIFile(
            id=file_id,
            object="file",
            bytes=file_size,
            created_at=created_at,
            filename=file_name or file_id,
            purpose=purpose,
        )

    async def save_file_chunk(
        self,
        file_id: str,
        user_id: str = Storage.DEFAULT_USER_ID,
        chunk: bytes = None,
        purpose: str = Storage.DEFAULT_PURPOSE,
        offset: int = 0,
    ) -> None:
        """Save file chunk to disk at specified offset"""
        user_path = self._get_user_path(user_id)
        file_path = os.path.join(user_path, file_id)
        async with aiofiles.open(file_path, "r+b") as f:
            await f.seek(offset)
            await f.write(chunk)

    async def get_file(
        self, file_id: str, user_id: str = Storage.DEFAULT_USER_ID
    ) -> OpenAIFile:
        """Retrieve file metadata from disk"""
        user_path = self._get_user_path(user_id)
        file_path = os.path.join(user_path, file_id)
        if not os.path.exists(file_path):
            logger.error(f"File {file_id} not found, returning empty file")
            raise FileNotFoundError(f"File {file_id} not found")
        file_size = os.path.getsize(file_path)
        created_at = int(os.path.getctime(file_path))
        return OpenAIFile(
            id=file_id,
            object="file",
            bytes=file_size,
            created_at=created_at,
            filename=file_id,
            purpose=Storage.DEFAULT_PURPOSE,
        )

    async def get_file_content(
        self, file_id: str, user_id: str = Storage.DEFAULT_USER_ID
    ) -> bytes:
        """Retrieve file content from disk"""
        user_path = self._get_user_path(user_id)
        file_path = os.path.join(user_path, file_id)
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File {file_id} not found")
        async with aiofiles.open(file_path, "rb") as f:
            return await f.read()

    async def list_files(self, user_id: str = Storage.DEFAULT_USER_ID) -> List[str]:
        """List all files in storage"""
        user_path = self._get_user_path(user_id)
        return os.listdir(user_path)

    async def delete_file(self, file_id: str, user_id: str = Storage.DEFAULT_USER_ID):
        """Delete file from disk"""
        user_path = self._get_user_path(user_id)
        file_path = os.path.join(user_path, file_id)
        if os.path.exists(file_path):
            os.remove(file_path)
