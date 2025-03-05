from abc import ABC, abstractmethod
from typing import List

from vllm_router.services.files_service.openai_files import OpenAIFile


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
        """
        Save a file with the given parameters and returns an OpenAIFile object.

        Args:
            file_id (str, optional): Unique identifier for the file. Defaults to None.
            user_id (str, optional): ID of the user uploading the file. Defaults to DEFAULT_USER_ID.
            file_name (str, optional): Name of the file. Defaults to None.
            content (bytes, optional): Binary content of the file. Defaults to None.
            purpose (str, optional): Purpose of the file upload. Defaults to DEFAULT_PURPOSE.

        Returns:
            OpenAIFile: Object containing the saved file information.

        Notes:
            This is an abstract method that must be implemented by subclasses.
        """
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
        """
        Save a chunk of a file in a streaming upload process.

        This abstract method is designed for handling streamed file uploads, allowing
        chunks of data to be saved incrementally.

        Args:
            file_id (str): The unique identifier for the file being uploaded.
            user_id (str, optional): The ID of the user uploading the file.
                Defaults to DEFAULT_USER_ID.
            chunk (bytes, optional): The binary data chunk to be saved.
                Defaults to None.
            purpose (str, optional): The intended use of the file.
                Defaults to DEFAULT_PURPOSE.
            offset (int, optional): The position in the file where this chunk should be written.
                Defaults to 0.

        Returns:
            None

        Notes:
            This method is specifically designed for streaming uploads where a file is sent
            in multiple chunks rather than as a single upload. Each chunk is saved at the
            specified offset position.
        """
        pass

    @abstractmethod
    async def get_file(
        self, file_id: str, user_id: str = DEFAULT_USER_ID
    ) -> OpenAIFile:
        """
        Retrieve file metadata from the storage.

        Args:
            file_id (str): The unique identifier for the file.
            user_id (str, optional): The ID of the user who owns the file.
                Defaults to DEFAULT_USER_ID.

        Returns:
            OpenAIFile: An OpenAIFile object containing the file metadata.
        """
        pass

    @abstractmethod
    async def get_file_content(
        self, file_id: str, user_id: str = DEFAULT_USER_ID
    ) -> bytes:
        """
        Retrieve the content of a file from the storage.

        Args:
            file_id (str): The unique identifier for the file.
            user_id (str, optional): The ID of the user who owns the file.
                Defaults to DEFAULT_USER_ID.

        Returns:
            bytes: The binary content of the file.
        """
        pass

    @abstractmethod
    async def list_files(self, user_id: str = DEFAULT_USER_ID) -> List[str]:
        """
        List all files stored for a given user.

        Args:
            user_id (str, optional): The ID of the user whose files should be listed.
                Defaults to DEFAULT_USER_ID.

        Returns:
            List[str]: A list of file IDs for the user.
        """
        pass

    @abstractmethod
    async def delete_file(self, file_id: str, user_id: str = DEFAULT_USER_ID):
        """
        Delete a file from the storage.

        Args:
            file_id (str): The unique identifier for the file to be deleted.
            user_id (str, optional): The ID of the user who owns the file.
                Defaults to DEFAULT_USER_ID.
        """
        pass


def initialize_storage(storage_type: str, base_path: str = None) -> Storage:
    """
    Initialize a file storage object based on the specified storage type.

    It is the factory method for creating the appropriate storage object based on the
    configuration provided.

    TODO(gaocegege): Make storage_type an enum, and the storage related variables
    like base_path should be in a config object.
    """
    if storage_type == "local_file":
        from vllm_router.services.files_service.file_storage import FileStorage

        return FileStorage(base_path)
    else:
        raise ValueError(f"Unsupported storage type: {storage_type}")
