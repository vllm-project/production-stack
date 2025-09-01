import time
from typing import List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from vllm_router.log import init_logger

logger = init_logger(__name__)


class OpenAIBaseModel(BaseModel):
    # OpenAI API does allow extra fields
    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def __log_extra_fields__(cls, data):
        if isinstance(data, dict):
            # Get all class field names and their potential aliases
            field_names = set()
            for field_name, field in cls.model_fields.items():
                field_names.add(field_name)
                if hasattr(field, "alias") and field.alias:
                    field_names.add(field.alias)

            # Compare against both field names and aliases
            extra_fields = data.keys() - field_names
            if extra_fields:
                logger.warning(
                    "The following fields were present in the request "
                    "but ignored: %s",
                    extra_fields,
                )
        return data


class ErrorResponse(OpenAIBaseModel):
    object: str = "error"
    message: str
    type: str
    param: Optional[str] = None
    code: int


class ModelCard(OpenAIBaseModel):
    id: str
    object: str = "model"
    created: int = Field(default_factory=lambda: int(time.time()))
    owned_by: str = "vllm"
    root: Optional[str] = None
    parent: Optional[str] = None


class ModelList(OpenAIBaseModel):
    object: str = "list"
    data: List[ModelCard] = Field(default_factory=list)


# ===== Core Request Models =====
# Based on vLLM official protocol.py definitions

class ChatCompletionRequest(OpenAIBaseModel):
    """ChatCompletion API request model based on OpenAI specification"""
    
    # Core required fields
    messages: List[dict]  # Simplified message type to avoid complex nested definitions
    model: Optional[str] = None
    
    # Core sampling parameters
    max_tokens: Optional[int] = None
    max_completion_tokens: Optional[int] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    frequency_penalty: Optional[float] = 0.0
    presence_penalty: Optional[float] = 0.0
    
    # Core control parameters
    stream: Optional[bool] = False
    stop: Optional[Union[str, List[str]]] = None
    n: Optional[int] = 1
    
    # Other common parameters
    seed: Optional[int] = None
    user: Optional[str] = None


class CompletionRequest(OpenAIBaseModel):
    """Completion API request model based on OpenAI specification"""
    
    # Core required fields
    prompt: Optional[Union[str, List[str], List[int], List[List[int]]]] = None
    model: Optional[str] = None
    
    # Core sampling parameters
    max_tokens: Optional[int] = 16
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    frequency_penalty: Optional[float] = 0.0
    presence_penalty: Optional[float] = 0.0
    
    # Core control parameters
    stream: Optional[bool] = False
    stop: Optional[Union[str, List[str]]] = None
    n: int = 1
    echo: Optional[bool] = False
    
    # Other common parameters
    seed: Optional[int] = None
    user: Optional[str] = None
    best_of: Optional[int] = None
    logprobs: Optional[int] = None
    suffix: Optional[str] = None


class EmbeddingRequest(OpenAIBaseModel):
    """Embedding API request model based on OpenAI specification"""
    
    # Core required fields
    input: Union[str, List[str], List[int], List[List[int]]]
    model: Optional[str] = None
    
    # Core control parameters
    encoding_format: Optional[str] = "float"
    dimensions: Optional[int] = None
    user: Optional[str] = None
