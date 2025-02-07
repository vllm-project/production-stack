"""
This script uploads JSONL files to the server, which can be used to run
batch inference on the VLLM model.
"""

from pathlib import Path

import rich
from openai import OpenAI

# get the current directory
current_dir = Path(__file__).parent
# generate this file using `./generate_file.sh`
filepath = current_dir / "batch.jsonl"

# Modify OpenAI's API key and API base to use vLLM's API server.
openai_api_key = "EMPTY"
openai_api_base = "http://localhost:8000/v1"

client = OpenAI(
    api_key=openai_api_key,
    base_url=openai_api_base,
)


def from_in_memory() -> None:
    file = client.files.create(
        file=filepath.read_bytes(),
        purpose="batch",
    )
    return file


if __name__ == "__main__":
    file = from_in_memory()

    # get the file according to the file id
    retrieved = client.files.retrieve(file.id)
    rich.print(retrieved)

    file_content = client.files.retrieve_content(file.id)
    rich.print(file_content.encode("utf-8"))
