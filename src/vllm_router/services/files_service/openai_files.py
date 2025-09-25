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
