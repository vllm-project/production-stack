"""
This script uploads JSONL files to the server, which can be used to run
batch inference on the VLLM model.
"""

import argparse
import time
from pathlib import Path

import rich
from openai import OpenAI

# get the current directory
current_dir = Path(__file__).parent

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="CLI arguments for OpenAI API configuration."
    )
    parser.add_argument(
        "--openai-api-key", type=str, default="NULL", help="Your OpenAI API key"
    )
    parser.add_argument(
        "--openai-api-base",
        type=str,
        default="http://localhost:8000/v1",
        help="Base URL for OpenAI API",
    )
    parser.add_argument(
        "--file-path",
        type=str,
        default="batch.jsonl",
        help="Path to the JSONL file to upload",
    )
    args = parser.parse_args()

    openai_api_key = args.openai_api_key
    openai_api_base = args.openai_api_base

    # generate this file using `./generate_file.sh`
    filepath = current_dir / args.file_path

    client = OpenAI(
        api_key=openai_api_key,
        base_url=openai_api_base,
    )

    file = client.files.create(
        file=filepath.read_bytes(),
        purpose="batch",
    )

    # get the file according to the file id
    retrieved = client.files.retrieve(file.id)
    print("Retrieved file:")
    rich.print(retrieved)

    file_content = client.files.content(file.id)
    print("File content:")
    rich.print(file_content.read().decode())
    file_content.close()

    # create a batch job
    batch = client.batches.create(
        input_file_id=file.id,
        endpoint="/completions",
        completion_window="1h",
    )
    print("Created batch job:")
    rich.print(batch)

    # retrieve the batch job
    retrieved_batch = client.batches.retrieve(batch.id)
    print("Retrieved batch job:")
    rich.print(retrieved_batch)

    # list all batch jobs
    batches = client.batches.list()
    print("List of batch jobs:")
    rich.print(batches)

    # wait for the batch job to complete
    while retrieved_batch.status == "pending":
        time.sleep(5)
        retrieved_batch = client.batches.retrieve(batch.id)

    # get the output file content
    output_file = client.files.retrieve(retrieved_batch.output_file_id)
    print("Output file:")
    rich.print(output_file)

    output_file_content = client.files.content(output_file.id)
    print("Output file content:")
    rich.print(output_file_content.read().decode())
