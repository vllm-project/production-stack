"""
Args:
    --port: Port to run the server on
    --host: Host to run the server on
    --max-tokens: maximum number of tokens to generate in the response if max_tokens is not provided in the request
    --speed: number of tokens per second per request
"""

import argparse
import asyncio
import time
import uuid
from typing import Final

from fastapi import FastAPI, Request
from fastapi.responses import Response, StreamingResponse
from vllm.entrypoints.openai.protocol import (
    ChatCompletionRequest,
    ChatCompletionResponseStreamChoice,
    ChatCompletionStreamResponse,
    DeltaMessage,
    UsageInfo,
)

app = FastAPI()
GLOBAL_ARGS = None
MODEL_NAME = "fake_model_name"
NUM_RUNNING_REQUESTS = 0


async def generate_fake_response(
    request_id: str,
    model_name: str,
    num_tokens: int,
    tokens_per_sec: float,
):
    async def sleep_to_target(target: float):
        sleep_time = target - time.time()
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)

    start = time.time()
    global NUM_RUNNING_REQUESTS

    if GLOBAL_ARGS.ttft > 0:
        await asyncio.sleep(GLOBAL_ARGS.ttft)

    NUM_RUNNING_REQUESTS += 1
    created_time = int(time.time())
    chunk_object_type: Final = "chat.completion.chunk"

    choice_data = ChatCompletionResponseStreamChoice(
        index=0,
        delta=DeltaMessage(
            role="assistant",
            content="",
        ),
        logprobs=None,
        finish_reason=None,
    )
    chunk = ChatCompletionStreamResponse(
        id=request_id,
        object=chunk_object_type,
        created=created_time,
        choices=[choice_data],
        model=model_name,
    )
    data = chunk.model_dump_json(exclude_unset=True)
    token_batch = 20

    for i in range(num_tokens):
        if i % token_batch == 0:
            await sleep_to_target(start + i / tokens_per_sec)

        text = "Hello "
        choice_data = ChatCompletionResponseStreamChoice(
            index=0, delta=DeltaMessage(content=text), logprobs=None, finish_reason=None
        )
        chunk = ChatCompletionStreamResponse(
            id=request_id,
            object=chunk_object_type,
            created=created_time,
            choices=[choice_data],
            model=model_name,
        )
        data = chunk.model_dump_json(exclude_unset=True)
        yield f"data: {data}\n\n"

    await sleep_to_target(num_tokens / tokens_per_sec + start)

    choice_data = ChatCompletionResponseStreamChoice(
        index=0,
        delta=DeltaMessage(
            content="\n",
        ),
        logprobs=None,
        finish_reason="length",
    )

    chunk = ChatCompletionStreamResponse(
        id=request_id,
        object=chunk_object_type,
        created=created_time,
        choices=[choice_data],
        model=model_name,
    )

    chunk.usage = UsageInfo(
        prompt_tokens=0,
        completion_tokens=num_tokens,
        total_tokens=num_tokens,
    )

    yield f"data: {data}\n\n"
    yield "data: [DONE]\n\n"

    NUM_RUNNING_REQUESTS -= 1
    elapsed = time.time() - start
    thp = num_tokens / elapsed
    print(
        f"Finished request with id: {request_id}, elapsed time {elapsed}, throughput {thp}"
    )


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest, raw_request: Request):
    global MODEL_NAME
    request_id = raw_request.get("x-request-id", f"fake_request_id_{uuid.uuid4()}")
    print(f"Received request with id: {request_id} at {time.time()}")
    model_name = MODEL_NAME
    num_tokens = request.max_tokens if request.max_tokens else 100
    tokens_per_sec = GLOBAL_ARGS.speed
    return StreamingResponse(
        generate_fake_response(request_id, model_name, num_tokens, tokens_per_sec),
        media_type="text/event-stream",
    )


@app.get("/metrics")
async def metrics():
    global NUM_RUNNING_REQUESTS, MODEL_NAME
    content = f"""# HELP vllm:num_requests_running Number of requests currently running on GPU.
# TYPE vllm:num_requests_running gauge
vllm:num_requests_running{{model_name="{MODEL_NAME}"}} {NUM_RUNNING_REQUESTS}
# HELP vllm:num_requests_swapped Number of requests swapped to CPU.
# TYPE vllm:num_requests_swapped gauge
vllm:num_requests_swapped{{model_name="{MODEL_NAME}"}} 0.0
# HELP vllm:num_requests_waiting Number of requests waiting to be processed.
# TYPE vllm:num_requests_waiting gauge
vllm:num_requests_waiting{{model_name="{MODEL_NAME}"}} 0.0"""

    return Response(content=content, media_type="text/plain")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--max-tokens", type=int, default=100)
    parser.add_argument("--speed", type=int, default=100)
    parser.add_argument("--ttft", type=float, default=0)
    args = parser.parse_args()
    return args


if __name__ == "__main__":
    import uvicorn

    GLOBAL_ARGS = parse_args()
    uvicorn.run(app, host=GLOBAL_ARGS.host, port=GLOBAL_ARGS.port)
