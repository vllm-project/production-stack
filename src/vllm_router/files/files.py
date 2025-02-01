from dataclasses import dataclass
from typing import Literal


@dataclass
class OpenAIFile:
    """
    Represents a file object

    https://platform.openai.com/docs/api-reference/files/object
    """

    id: str
    object: Literal["file"]
    bytes: int
    created_at: int
    filename: str
    purpose: str

    @classmethod
    def from_dict(cls, data: dict) -> "OpenAIFile":
        return cls(
            id=data["id"],
            object=data["object"],
            bytes=data["bytes"],
            created_at=data["created_at"],
            filename=data["filename"],
            purpose=data["purpose"],
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "object": self.object,
            "bytes": self.bytes,
            "created_at": self.created_at,
            "filename": self.filename,
            "purpose": self.purpose,
        }

    def metadata(self) -> dict:
        return {
            "id": self.id,
            "bytes": self.bytes,
            "created_at": self.created_at,
            "filename": self.filename,
            "purpose": self.purpose,
        }
