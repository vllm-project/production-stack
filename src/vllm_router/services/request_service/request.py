# --- Request Processing & Routing ---
# TODO: better request id system
import json
import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

from vllm_router.log import init_logger
from vllm_router.service_discovery import get_service_discovery

try:
    # Semantic cache integration
    from vllm_router.experimental.semantic_cache import (
        GetSemanticCache,
        enable_semantic_cache,
        initialize_semantic_cache,
        is_semantic_cache_enabled,
    )
    from vllm_router.experimental.semantic_cache_integration import (
        add_semantic_cache_args,
        check_semantic_cache,
        semantic_cache_hit_ratio,
        semantic_cache_hits,
        semantic_cache_latency,
        semantic_cache_misses,
        semantic_cache_size,
        store_in_semantic_cache,
    )

    semantic_cache_available = True
except ImportError:
    semantic_cache_available = False


logger = init_logger(__name__)


async def process_request(
    request: Request, body, backend_url, request_id, endpoint, debug_request=None
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
    is_streaming = False
    try:
        request_json = json.loads(body)
        is_streaming = request_json.get("stream", False)
    except:
        # If we can't parse the body as JSON, assume it's not streaming
        pass

    # For non-streaming requests, collect the full response to cache it properly
    full_response = bytearray() if not is_streaming else None

    async with request.app.state.httpx_client_wrapper().stream(
        method=request.method,
        url=backend_url + endpoint,
        headers=dict(request.headers),
        content=body,
        timeout=None,
    ) as backend_response:
        # Yield headers and status code first.
        yield backend_response.headers, backend_response.status_code
        # Stream response content.
        async for chunk in backend_response.aiter_bytes():
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
        cache_chunk = bytes(full_response) if full_response is not None else chunk
        await store_in_semantic_cache(
            endpoint=endpoint, method=request.method, body=body, chunk=cache_chunk
        )


async def route_general_request(request: Request, endpoint: str):
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

    in_router_time = time.time()
    request_id = str(uuid.uuid4())
    request_body = await request.body()
    request_json = await request.json()  # TODO (ApostaC): merge two awaits into one
    requested_model = request_json.get("model", None)
    if requested_model is None:
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid request: missing 'model' in request body."},
        )

    # TODO (ApostaC): merge two awaits into one
    endpoints = get_service_discovery().get_endpoint_info()
    engine_stats = request.app.state.engine_stats_scraper.get_engine_stats()
    request_stats = request.app.state.request_stats_monitor.get_request_stats(
        time.time()
    )

    endpoints = list(filter(lambda x: x.model_name == requested_model, endpoints))
    if not endpoints:
        return JSONResponse(
            status_code=400, content={"error": f"Model {requested_model} not found."}
        )

    logger.debug(f"Routing request {request_id} for model: {requested_model}")
    server_url = request.app.state.router.route_request(
        endpoints, engine_stats, request_stats, request
    )
    curr_time = time.time()
    logger.info(
        f"Routing request {request_id} to {server_url} at {curr_time}, process time = {curr_time - in_router_time:.4f}"
    )
    stream_generator = process_request(
        request,
        request_body,
        server_url,
        request_id,
        endpoint=endpoint,
    )
    headers, status_code = await anext(stream_generator)
    return StreamingResponse(
        stream_generator,
        status_code=status_code,
        headers={key: value for key, value in headers.items()},
        media_type="text/event-stream",
    )
