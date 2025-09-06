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

import asyncio

# --- Request Processing & Routing ---
import json
import os
import time
import uuid
from typing import Optional

import aiohttp
import msgspec
import zmq
import zmq.asyncio
from fastapi import BackgroundTasks, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

try:
    from lmcache.v1.storage_backend.connector.nixl_connector_v3 import (
        NixlMsg,
    )
except ImportError:
    pass
from requests import JSONDecodeError

from vllm_router.log import init_logger
from vllm_router.routers.routing_logic import (
    DisaggregatedPrefillRouter,
    KvawareRouter,
    PrefixAwareRouter,
)
from vllm_router.service_discovery import get_service_discovery
from vllm_router.services.request_service.rewriter import (
    get_request_rewriter,
    is_request_rewriter_initialized,
)
from vllm_router.utils import replace_model_in_request_body, update_content_length

try:
    # Semantic cache integration
    from vllm_router.experimental.semantic_cache_integration import (
        store_in_semantic_cache,
    )

    semantic_cache_available = True
except ImportError:
    semantic_cache_available = False


logger = init_logger(__name__)

finished_reqs = set()
run_proxy = True
zmq_ctx = zmq.asyncio.Context()


async def zmq_pull_server():
    try:
        socket = zmq_ctx.socket(zmq.PULL)
        try:
            from vllm_router.app import app

            proxy_host = app.state.args.nixl_proxy_host
            proxy_port = app.state.args.nixl_proxy_port
        except Exception as e:
            logger.error(f"Failed to get proxy host and port from app state: {e}")
        proxy_url = f"{proxy_host}:{proxy_port}"
        socket.bind(f"tcp://{proxy_url}")
        logger.info(f"ZMQ proxy server started on {proxy_url}")
    except Exception as e:
        logger.error(f"Failed to bind ZMQ socket to {proxy_url}: {e}")
        socket.close()
        return

    while run_proxy:
        try:
            msg_bytes = await socket.recv()
            msg = msgspec.msgpack.decode(msg_bytes, type=NixlMsg)
            req_id = msg.req_id
            finished_reqs.add(req_id)
            logger.info(f"Prefill of req {req_id} done.")
        except zmq.Again:
            await asyncio.sleep(0.01)  # Avoid busy loop
        except Exception as e:
            logger.error(f"ZMQ Error in message processing: {e}")
            break

    socket.close()
    logger.info("ZMQ PULL server stopped.")


# ZMQ task will be created in the FastAPI lifespan manager
zmq_task = None


async def start_zmq_task():
    """Start the ZMQ pull server task."""
    global zmq_task
    if zmq_task is None:
        zmq_task = asyncio.create_task(zmq_pull_server())
        logger.info("ZMQ task started")

        # Add a small delay to allow the task to start and potentially log any errors
        await asyncio.sleep(0.1)


async def stop_zmq_task():
    """Stop the ZMQ pull server task."""
    global zmq_task, run_proxy
    if zmq_task is not None:
        run_proxy = False
        zmq_task.cancel()
        try:
            await zmq_task
        except asyncio.CancelledError:
            pass
        zmq_task = None
        logger.info("ZMQ task stopped")


# TODO: (Brian) check if request is json beforehand
async def process_request(
    request: Request,
    body,
    backend_url,
    request_id,
    endpoint,
    background_tasks: BackgroundTasks,
    debug_request=None,
):
    """
    Process a request by sending it to the chosen backend.

    Args:
        request(Request): Request object.
        body: The content of the request to send to the backend.
        backend_url: The URL of the backend to send the request to.
        request_id: A unique identifier for the request.
        endpoint: The endpoint to send the request to on the backend.
        debug_request: The original request object from the client, used for
            optional debug logging.

    Yields:
        The response headers and status code, followed by the response content.

    Raises:
        HTTPError: If the backend returns a 4xx or 5xx status code.
    """
    first_token = False
    total_len = 0
    start_time = time.time()
    request.app.state.request_stats_monitor.on_new_request(
        backend_url, request_id, start_time
    )
    # Check if this is a streaming request
    try:
        request_json = json.loads(body)
        is_streaming = request_json.get("stream", False)
    except JSONDecodeError:
        # If we can't parse the body as JSON, assume it's not streaming
        raise HTTPException(status=400, detail="Request body is not JSON parsable.")

    # For non-streaming requests, collect the full response to cache it properly
    full_response = bytearray()

    async with request.app.state.aiohttp_client_wrapper().request(
        method=request.method,
        url=backend_url + endpoint,
        headers=dict(request.headers),
        data=body,
        timeout=aiohttp.ClientTimeout(total=None),
    ) as backend_response:
        # Yield headers and status code first.
        yield backend_response.headers, backend_response.status
        # Stream response content.
        async for chunk in backend_response.content.iter_any():
            total_len += len(chunk)
            if not first_token:
                first_token = True
                request.app.state.request_stats_monitor.on_request_response(
                    backend_url, request_id, time.time()
                )
            # For non-streaming requests, collect the full response
            if full_response is not None:
                full_response.extend(chunk)
            yield chunk

    request.app.state.request_stats_monitor.on_request_complete(
        backend_url, request_id, time.time()
    )

    # if debug_request:
    #    logger.debug(f"Finished the request with request id: {debug_request.headers.get('x-request-id', None)} at {time.time()}")
    # Store in semantic cache if applicable
    # Use the full response for non-streaming requests, or the last chunk for streaming
    if request.app.state.semantic_cache_available:
        cache_chunk = bytes(full_response) if not is_streaming else chunk
        await store_in_semantic_cache(
            endpoint=endpoint, method=request.method, body=body, chunk=cache_chunk
        )
    if background_tasks and getattr(request.app.state, "callbacks", None):
        background_tasks.add_task(
            request.app.state.callbacks.post_request, request, full_response
        )


async def route_general_request(
    request: Request, endpoint: str, background_tasks: BackgroundTasks
):
    """
    Route the incoming request to the backend server and stream the response back to the client.

    This function extracts the requested model from the request body and retrieves the
    corresponding endpoints. It uses routing logic to determine the best server URL to handle
    the request, then streams the request to that server. If the requested model is not available,
    it returns an error response.

    Args:
        request (Request): The incoming HTTP request.
        endpoint (str): The endpoint to which the request should be routed.

    Returns:
        StreamingResponse: A response object that streams data from the backend server to the client.
    """
    if isinstance(request.app.state.router, DisaggregatedPrefillRouter):
        response = await route_disaggregated_prefill_request(
            request, endpoint, background_tasks
        )
        return response
    in_router_time = time.time()
    # Same as vllm, Get request_id from X-Request-Id header if available
    request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    request_body = await request.body()
    request_json = await request.json()  # TODO (ApostaC): merge two awaits into one

    if request.query_params:
        request_endpoint = request.query_params.get("id")
    else:
        request_endpoint = None

    if getattr(request.app.state, "callbacks", None) and (
        response_overwrite := request.app.state.callbacks.pre_request(
            request, request_body, request_json
        )
    ):
        response_overwrite.headers["X-Request-Id"] = request_id
        return response_overwrite

    requested_model = request_json.get("model", None)
    if requested_model is None:
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid request: missing 'model' in request body."},
            headers={"X-Request-Id": request_id},
        )

    # Apply request rewriting if enabled
    if is_request_rewriter_initialized():
        rewriter = get_request_rewriter()
        rewritten_body = rewriter.rewrite_request(
            request_body, requested_model, endpoint
        )
        logger.info(f"Request for model {requested_model} was rewritten")
        request_body = rewritten_body
        # Update request_json if the body was rewritten
        try:
            request_json = json.loads(request_body)
        except JSONDecodeError:
            logger.warning("Failed to parse rewritten request body as JSON")
            raise HTTPException(
                status_code=400, detail="Request body is not JSON parsable."
            )

    # TODO (ApostaC): merge two awaits into one
    service_discovery = get_service_discovery()
    endpoints = service_discovery.get_endpoint_info()

    aliases = getattr(service_discovery, "aliases", None)
    if aliases and requested_model in aliases.keys():
        requested_model = aliases[requested_model]
        request_body = replace_model_in_request_body(request_json, requested_model)
        update_content_length(request, request_body)

    if not request_endpoint:
        endpoints = list(
            filter(
                lambda x: requested_model in x.model_names and not x.sleep,
                endpoints,
            )
        )
        engine_stats = request.app.state.engine_stats_scraper.get_engine_stats()
        request_stats = request.app.state.request_stats_monitor.get_request_stats(
            time.time()
        )
    else:
        endpoints = list(
            filter(
                lambda x: requested_model in x.model_names
                and x.Id == request_endpoint
                and not x.sleep,
                endpoints,
            )
        )

    if not endpoints:
        return JSONResponse(
            status_code=400,
            content={
                "error": f"Model {requested_model} not found or vLLM engine is sleeping."
            },
        )

    logger.debug(f"Routing request {request_id} for model: {requested_model}")
    if request_endpoint:
        server_url = endpoints[0].url
        logger.debug(
            f"Routing request {request_id} to engine with Id: {endpoints[0].Id}"
        )

    elif isinstance(request.app.state.router, KvawareRouter) or isinstance(
        request.app.state.router, PrefixAwareRouter
    ):
        server_url = await request.app.state.router.route_request(
            endpoints, engine_stats, request_stats, request, request_json
        )
    else:
        server_url = request.app.state.router.route_request(
            endpoints, engine_stats, request_stats, request
        )

    curr_time = time.time()
    # Extract actual session ID from request headers for logging
    session_key = (
        getattr(request.app.state.router, "session_key", None)
        if hasattr(request.app.state.router, "session_key")
        else None
    )
    session_id = (
        request.headers.get(session_key, None) if session_key is not None else None
    )
    session_id_display = session_id if session_id is not None else "None"

    # Debug logging to help troubleshoot session ID extraction
    logger.debug(
        f"Debug session extraction - Router type: {type(request.app.state.router).__name__}"
    )
    logger.debug(f"Debug session extraction - Session key config: {session_key}")
    logger.debug(f"Debug session extraction - Request headers: {dict(request.headers)}")
    logger.debug(f"Debug session extraction - Extracted session ID: {session_id}")

    logger.info(
        f"Routing request {request_id} with session id {session_id_display} to {server_url} at {curr_time}, process time = {curr_time - in_router_time:.4f}"
    )
    stream_generator = process_request(
        request,
        request_body,
        server_url,
        request_id,
        endpoint,
        background_tasks,
    )
    headers, status = await anext(stream_generator)
    headers_dict = {key: value for key, value in headers.items()}
    headers_dict["X-Request-Id"] = request_id
    return StreamingResponse(
        stream_generator,
        status_code=status,
        headers=headers_dict,
        media_type="text/event-stream",
    )


# TODO: Combine with send_request_to_tokenizer and send_request_to_decode
async def send_request_to_prefiller(
    client: aiohttp.ClientSession, endpoint: str, req_data: dict, request_id: str
):
    """Send a request to a prefiller service."""
    req_data = req_data.copy()
    req_data["max_tokens"] = 1
    if "max_completion_tokens" in req_data:
        req_data["max_completion_tokens"] = 1

    headers = {
        "Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY')}",
        "X-Request-Id": request_id,
    }

    async with client.post(endpoint, json=req_data, headers=headers) as response:
        response.raise_for_status()
        return await response.json()


async def send_request_to_tokenizer(
    client: aiohttp.ClientSession, endpoint: str, req_data: dict, request_id: str
):
    """
    Send a request to a tokenizer service.
    """
    headers = {
        "Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY')}",
        "X-Request-Id": request_id,
    }

    async with client.post(endpoint, json=req_data, headers=headers) as response:
        response.raise_for_status()
        return await response.json()


async def send_request_to_decode(
    client: aiohttp.ClientSession, endpoint: str, req_data: dict, request_id: str
):
    """Asynchronously stream the response from a service using a persistent client."""
    headers = {
        "Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY')}",
        "X-Request-Id": request_id,
    }

    async with client.post(endpoint, json=req_data, headers=headers) as response:
        response.raise_for_status()
        async for chunk in response.content.iter_any():
            yield chunk


async def wait_decode_kv_ready(req_id: str):
    while req_id not in finished_reqs:
        await asyncio.sleep(0.0001)  # sleep for 0.1 ms
    logger.debug(f"Prefill node signaled kv ready for req {req_id}")
    finished_reqs.remove(req_id)


async def route_disaggregated_prefill_request(
    request: Request,
    endpoint: str,
    background_tasks: BackgroundTasks,
):
    in_router_time = time.time()
    # Same as vllm, Get request_id from X-Request-Id header if available
    request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    request_json = await request.json()

    orig_max_tokens = request_json.get("max_tokens", 0)
    stream_options = request_json.pop("stream_options", None)

    # # Check if client sessions are initialized, if not, try to initialize them
    # if not hasattr(request.app.state, 'prefill_client') or request.app.state.prefill_client is None:
    #     logger.warning("prefill_client not initialized, attempting to initialize client sessions")
    #     try:
    #         from vllm_router.service_discovery import get_service_discovery
    #         service_discovery = get_service_discovery()
    #         if hasattr(service_discovery, '_reinitialize_client_sessions'):
    #             logger.info("In route_disaggregated_prefill_request: Calling _reinitialize_client_sessions")
    #             await service_discovery._reinitialize_client_sessions()
    #             logger.info("Successfully initialized client sessions")
    #         else:
    #             logger.error("Service discovery does not have _reinitialize_client_sessions method")
    #     except Exception as e:
    #         logger.error(f"Failed to initialize client sessions: {e}")
    #         return JSONResponse(
    #             status_code=500,
    #             content={
    #                 "error": {
    #                     "message": "Failed to initialize client sessions",
    #                     "type": "initialization_error",
    #                     "code": 500,
    #                 }
    #             },
    #             headers={"X-Request-Id": request_id},
    #         )

    st = time.time()
    try:
        # Step 1: Tokenize the prompt
        # request_json {'model': 'facebook/opt-125m', 'prompt': 'What date is today?', 'max_tokens': 20, 'temperature': 0.0}
        # # print every key-value pair in prefill_client
        # for key, value in request.app.state.prefill_client.__dict__.items():
        #     print(f"{key}: {value}")

        tokenize_output = await send_request_to_tokenizer(
            request.app.state.prefill_client,
            "/tokenize",
            {"prompt": request_json["prompt"]},
            request_id,
        )
        # tokenize_output {'count': 6, 'max_model_len': 2048, 'tokens': [2, 2264, 1248, 16, 452, 116], 'token_strs': None}

        # Update request with tokenized prompt
        request_json["prompt"] = tokenize_output["tokens"]
        request_json["max_tokens"] = 1

        # Step 2: Create disagg_spec for KV transfer
        disagg_spec = {
            "req_id": request_id,
            "receiver_host": request.app.state.args.nixl_peer_host,
            "receiver_init_port": [request.app.state.args.nixl_peer_init_port],
            "receiver_alloc_port": [request.app.state.args.nixl_peer_alloc_port],
        }
        # disagg_spec = {
        #     "req_id": request_id,
        #     "receiver_host": "0.0.0.0",
        #     "receiver_init_port": [7300],
        #     "receiver_alloc_port": [7400],
        # }

        request_json["kv_transfer_params"] = {
            "ret_first_tok": True,
            "disagg_spec": disagg_spec,
        }
        request_json["stream"] = False

        # Step 3: Send to prefiller
        prefill_output = await send_request_to_prefiller(
            request.app.state.prefill_client, endpoint, request_json, request_id
        )
        et = time.time()
        logger.info(f"{request_id} prefill time (TTFT): {et - st:.4f}")
        logger.info(
            f"Routing request {request_id} with session id None to {request.app.state.prefill_client._base_url} at {et}, process time = {et - in_router_time:.4f}"
        )

        # Step 4: Prepare decode request
        request_json["max_tokens"] = orig_max_tokens - 1
        request_json["prompt"].append(prefill_output["kv_transfer_params"]["first_tok"])
        request_json.pop("kv_transfer_params")
        request_json["stream"] = True
        if stream_options is not None:
            request_json["stream_options"] = stream_options

    except aiohttp.ClientResponseError as e:
        logger.error(f"HTTP error in prefiller: {e}", exc_info=True)
        return JSONResponse(
            status_code=e.status,
            content={
                "error": {
                    "message": f"Prefiller error: {e.message}",
                    "type": "prefiller_error",
                    "code": e.status,
                }
            },
            headers={"X-Request-Id": request_id},
        )
    except Exception as e:
        logger.error(f"Unexpected error in prefiller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "message": f"Prefiller error: {str(e)}",
                    "type": "prefiller_error",
                    "code": 500,
                }
            },
            headers={"X-Request-Id": request_id},
        )

    async def generate_stream():
        try:
            # Yield initial chunk with prefill data
            head_chunk = {
                "id": prefill_output["id"],
                "object": "text_completion",
                "created": prefill_output["created"],
                "model": prefill_output["model"],
                "choices": [
                    {
                        "index": 0,
                        "text": prefill_output["choices"][0]["text"],
                        "logprobs": None,
                        "finish_reason": None,
                        "stop_reason": None,
                    }
                ],
                "usage": None,
            }
            yield (
                "data: " + json.dumps(head_chunk, separators=(",", ":")) + "\n\n"
            ).encode()

            await wait_decode_kv_ready(request_id)

            # Stream the rest from decode service
            async for chunk in send_request_to_decode(
                request.app.state.decode_client, endpoint, request_json, request_id
            ):
                yield chunk
        except aiohttp.ClientResponseError as e:
            logger.error(f"HTTP error in decoder: {e}", exc_info=True)
            try:
                error_text = e.message
            except Exception:
                error_text = f"HTTP {e.status}"
            # Yield error as JSON response
            error_response = {
                "error": {
                    "message": f"Decoder error: {error_text}",
                    "type": "decoder_error",
                    "code": e.status,
                }
            }
            yield json.dumps(error_response).encode("utf-8")
        except Exception as e:
            logger.error(f"Unexpected error in decoder: {e}", exc_info=True)
            # Yield error as JSON response
            error_response = {
                "error": {
                    "message": f"Decoder error: {str(e)}",
                    "type": "decoder_error",
                    "code": 500,
                }
            }
            yield json.dumps(error_response).encode("utf-8")

    curr_time = time.time()
    logger.info(
        f"Routing request {request_id} with session id None to {request.app.state.decode_client._base_url} at {curr_time}, process time = {curr_time - et:.4f}"
    )

    return StreamingResponse(
        generate_stream(),
        media_type="application/json",
        headers={"X-Request-Id": request_id},
    )


async def route_sleep_wakeup_request(
    request: Request,
    endpoint: str,
    background_tasks: BackgroundTasks,
):
    in_router_time = time.time()
    # Same as vllm, Get request_id from X-Request-Id header if available
    request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())

    if request.query_params:
        request_endpoint = request.query_params.get("id")
    else:
        request_endpoint = None

    if request_endpoint is None:
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid request: missing target Engine Id."},
            headers={"X-Request-Id": request_id},
        )

    service_discovery = get_service_discovery()
    endpoints = service_discovery.get_endpoint_info()

    endpoints = list(filter(lambda x: x.Id == request_endpoint, endpoints))
    if not endpoints:
        return JSONResponse(
            status_code=400,
            content={"error": f"Engine with Id {request_endpoint} not found."},
        )
    logger.debug(f"Routing request {request_id} to engine with Id: {endpoints[0].Id}")

    server_url = endpoints[0].url
    curr_time = time.time()
    logger.info(
        f"Routing request {request_id} to {server_url} at {curr_time}, process time = {curr_time - in_router_time:.4f}"
    )

    headers = {
        "X-Request-Id": request_id,
    }

    if VLLM_API_KEY := os.getenv("VLLM_API_KEY"):
        logger.info("Using vllm server authentication")
        headers["Authorization"] = f"Bearer {VLLM_API_KEY}"

    url = server_url + endpoint

    async with aiohttp.ClientSession() as client:
        if endpoint == "/is_sleeping":
            async with client.get(url, headers=headers) as response:
                response.raise_for_status()
                return await response.json()
        else:
            request_body = await request.body()
            response_status = None
            if request_body:
                req_data = json.loads(request_body)
                async with client.post(url, json=req_data, headers=headers) as response:
                    response.raise_for_status()
                    response_status = response.status
            else:
                async with client.post(url, headers=headers) as response:
                    response.raise_for_status()
                    response_status = response.status

            pod_name = endpoints[0].pod_name
            if endpoint == "/sleep":
                service_discovery.add_sleep_label(pod_name)
            elif endpoint == "/wake_up":
                service_discovery.remove_sleep_label(pod_name)

            return JSONResponse(
                status_code=response_status,
                content={"status": "success"},
                headers={"X-Request-Id": request_id},
            )


async def route_general_transcriptions(
    request: Request,
    endpoint: str,  # "/v1/audio/transcriptions"
    background_tasks: BackgroundTasks,
):
    """Handles audio transcription requests by parsing form data and proxying to backend."""

    request_id = request.headers.get("X-Request-Id", str(uuid.uuid4()))

    # --- 1. Form parsing ---
    try:
        form = await request.form()

        # Extract parameters from the form data
        file: UploadFile = form["file"]
        model: str = form["model"]
        prompt: Optional[str] = form.get("prompt", None)
        response_format: Optional[str] = form.get("response_format", "json")
        temperature_str: Optional[str] = form.get("temperature", None)
        temperature: Optional[float] = (
            float(temperature_str) if temperature_str is not None else None
        )
        language: Optional[str] = form.get("language", "en")
    except KeyError as e:
        return JSONResponse(
            status_code=400,
            content={"error": f"Invalid request: missing '{e.args[0]}' in form data."},
        )

    logger.debug("==== Enter audio_transcriptions ====")
    logger.debug("Received upload: %s (%s)", file.filename, file.content_type)
    logger.debug(
        "Params: model=%s prompt=%r response_format=%r temperature=%r language=%s",
        model,
        prompt,
        response_format,
        temperature,
        language,
    )

    # --- 2. Service Discovery and Routing ---
    # Access singletons via request.app.state for consistent style
    service_discovery = (
        get_service_discovery()
    )  # This one is often still accessed directly via its get function
    router = request.app.state.router  # Access router from app.state
    engine_stats_scraper = (
        request.app.state.engine_stats_scraper
    )  # Access engine_stats_scraper from app.state
    request_stats_monitor = (
        request.app.state.request_stats_monitor
    )  # Access request_stats_monitor from app.state

    endpoints = service_discovery.get_endpoint_info()

    logger.debug("==== Total endpoints ====")
    logger.debug(endpoints)
    logger.debug("==== Total endpoints ====")

    # filter the endpoints url by model name and label for transcriptions
    transcription_endpoints = [
        ep
        for ep in endpoints
        if model == ep.model_name
        and ep.model_label == "transcription"
        and not ep.sleep  # Added ep.sleep == False
    ]

    logger.debug("====List of transcription endpoints====")
    logger.debug(transcription_endpoints)
    logger.debug("====List of transcription endpoints====")

    if not transcription_endpoints:
        logger.error("No transcription backend available for model %s", model)
        return JSONResponse(
            status_code=404,
            content={"error": f"No transcription backend for model {model}"},
        )

    # grab the current engine and request stats
    engine_stats = engine_stats_scraper.get_engine_stats()
    request_stats = request_stats_monitor.get_request_stats(time.time())

    # pick one using the router's configured logic (roundrobin, least-loaded, etc.)
    chosen_url = router.route_request(
        transcription_endpoints,
        engine_stats,
        request_stats,
        request,
    )

    logger.debug("Proxying transcription request to %s", chosen_url)

    # --- 3. Prepare and Proxy the Request ---
    payload_bytes = await file.read()
    files = {"file": (file.filename, payload_bytes, file.content_type)}

    data = {"model": model, "language": language}

    if prompt:
        data["prompt"] = prompt

    if response_format:
        data["response_format"] = response_format

    if temperature is not None:
        data["temperature"] = str(temperature)

    logger.info("Proxying transcription request for model %s to %s", model, chosen_url)

    logger.debug("==== data payload keys ====")
    logger.debug(list(data.keys()))
    logger.debug("==== data payload keys ====")

    try:
        client = request.app.state.aiohttp_client_wrapper()

        form_data = aiohttp.FormData()

        # add file data
        for key, (filename, content, content_type) in files.items():
            form_data.add_field(
                key, content, filename=filename, content_type=content_type
            )

        # add from data
        for key, value in data.items():
            form_data.add_field(key, value)

        backend_response = await client.post(
            f"{chosen_url}{endpoint}",
            data=form_data,
            timeout=aiohttp.ClientTimeout(total=300),
        )

        # --- 4. Return the response ---
        response_content = await backend_response.json()
        headers = {
            k: v
            for k, v in backend_response.headers.items()
            if k.lower() not in ("content-encoding", "transfer-encoding", "connection")
        }

        headers["X-Request-Id"] = request_id

        return JSONResponse(
            content=response_content,
            status_code=backend_response.status,
            headers=headers,
        )
    except aiohttp.ClientResponseError as response_error:
        if response_error.response is not None:
            try:
                error_content = await response_error.response.json()
            except (
                aiohttp.ContentTypeError,
                json.JSONDecodeError,
                aiohttp.ClientError,
            ):
                # If JSON parsing fails, get text content
                try:
                    text_content = await response_error.response.text()
                    error_content = {"error": text_content}
                except aiohttp.ClientError:
                    error_content = {
                        "error": f"HTTP {response_error.status}: {response_error.message}"
                    }
        else:
            error_content = {
                "error": f"HTTP {response_error.status}: {response_error.message}"
            }
        return JSONResponse(status_code=response_error.status, content=error_content)
    except aiohttp.ClientError as client_error:
        return JSONResponse(
            status_code=503,
            content={"error": f"Failed to connect to backend: {str(client_error)}"},
        )
