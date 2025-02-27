import argparse
import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import uvicorn
from fastapi import FastAPI, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, Gauge, generate_latest

from vllm_router.batch import BatchProcessor, initialize_batch_processor
from vllm_router.engine_stats import GetEngineStatsScraper, InitializeEngineStatsScraper
from vllm_router.files import Storage, initialize_storage
from vllm_router.httpx_client import HTTPXClientWrapper
from vllm_router.protocols import ModelCard, ModelList
from vllm_router.request_stats import (
    GetRequestStatsMonitor,
    InitializeRequestStatsMonitor,
)
from vllm_router.routing_logic import GetRoutingLogic, InitializeRoutingLogic
from vllm_router.service_discovery import (
    GetServiceDiscovery,
    InitializeServiceDiscovery,
    ServiceDiscoveryType,
)
from vllm_router.utils import set_ulimit, validate_url
from vllm_router.version import __version__

httpx_client_wrapper = HTTPXClientWrapper()
logger = logging.getLogger("uvicorn")


@asynccontextmanager
async def lifespan(app: FastAPI):
    httpx_client_wrapper.start()
    if hasattr(app.state, "batch_processor"):
        await app.state.batch_processor.initialize()
    yield
    await httpx_client_wrapper.stop()


app = FastAPI(lifespan=lifespan)

# --- Prometheus Gauges ---
# Existing metrics
num_requests_running = Gauge(
    "vllm:num_requests_running", "Number of running requests", ["server"]
)
num_requests_waiting = Gauge(
    "vllm:num_requests_waiting", "Number of waiting requests", ["server"]
)
current_qps = Gauge("vllm:current_qps", "Current Queries Per Second", ["server"])
avg_decoding_length = Gauge(
    "vllm:avg_decoding_length", "Average Decoding Length", ["server"]
)
num_prefill_requests = Gauge(
    "vllm:num_prefill_requests", "Number of Prefill Requests", ["server"]
)
num_decoding_requests = Gauge(
    "vllm:num_decoding_requests", "Number of Decoding Requests", ["server"]
)

# New metrics per dashboard update
healthy_pods_total = Gauge(
    "vllm:healthy_pods_total", "Number of healthy vLLM pods", ["server"]
)
avg_latency = Gauge(
    "vllm:avg_latency", "Average end-to-end request latency", ["server"]
)
avg_itl = Gauge("vllm:avg_itl", "Average Inter-Token Latency", ["server"])
num_requests_swapped = Gauge(
    "vllm:num_requests_swapped", "Number of swapped requests", ["server"]
)


# --- Request Processing & Routing ---
# TODO: better request id system
async def process_request(
    method, header, body, backend_url, request_id, endpoint, debug_request=None
):
    """
    Process a request by sending it to the chosen backend.

    Args:
        method: The HTTP method to use when sending the request to the backend.
        header: The headers to send with the request to the backend.
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
    app.state.request_stats_monitor.on_new_request(backend_url, request_id, start_time)

    client = httpx_client_wrapper()
    async with client.stream(
        method=method,
        url=backend_url + endpoint,
        headers=dict(header),
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
                app.state.request_stats_monitor.on_request_response(
                    backend_url, request_id, time.time()
                )
            yield chunk

    app.state.request_stats_monitor.on_request_complete(
        backend_url, request_id, time.time()
    )

    # if debug_request:
    #    logger.debug(f"Finished the request with request id: {debug_request.headers.get('x-request-id', None)} at {time.time()}")


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
    endpoints = GetServiceDiscovery().get_endpoint_info()
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
        request.method,
        request.headers,
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


# --- File Endpoints ---
@app.post("/v1/files")
async def route_files(request: Request):
    """
    Handle file upload requests and save the files to the configured storage.

    Args:
        request (Request): The incoming HTTP request.

    Returns:
        JSONResponse: A JSON response containing the file metadata.

    Raises:
        JSONResponse: A JSON response with a 400 status code if the request is invalid,
            or a 500 status code if an error occurs during file saving.
    """
    form = await request.form()
    purpose = form.get("purpose", "unknown")
    if "file" not in form:
        return JSONResponse(
            status_code=400, content={"error": "Missing required parameter 'file'"}
        )
    file_obj: UploadFile = form["file"]
    file_content = await file_obj.read()
    try:
        storage: Storage = app.state.batch_storage
        file_info = await storage.save_file(
            file_name=file_obj.filename, content=file_content, purpose=purpose
        )
        return JSONResponse(content=file_info.metadata())
    except Exception as e:
        return JSONResponse(
            status_code=500, content={"error": f"Failed to save file: {str(e)}"}
        )


@app.get("/v1/files/{file_id}")
async def route_get_file(file_id: str):
    try:
        storage: Storage = app.state.batch_storage
        file = await storage.get_file(file_id)
        return JSONResponse(content=file.metadata())
    except FileNotFoundError:
        return JSONResponse(
            status_code=404, content={"error": f"File {file_id} not found"}
        )


@app.get("/v1/files/{file_id}/content")
async def route_get_file_content(file_id: str):
    try:
        # TODO(gaocegege): Stream the file content with chunks to support
        # openai uploads interface.
        storage: Storage = app.state.batch_storage
        file_content = await storage.get_file_content(file_id)
        return Response(content=file_content)
    except FileNotFoundError:
        return JSONResponse(
            status_code=404, content={"error": f"File {file_id} not found"}
        )


@app.post("/v1/batches")
async def route_batches(request: Request):
    """Handle batch requests that process files with specified endpoints."""
    try:
        request_json = await request.json()

        # Validate required fields
        if "input_file_id" not in request_json:
            return JSONResponse(
                status_code=400,
                content={"error": "Missing required parameter 'input_file_id'"},
            )
        if "endpoint" not in request_json:
            return JSONResponse(
                status_code=400,
                content={"error": "Missing required parameter 'endpoint'"},
            )

        # Verify file exists
        storage: Storage = app.state.batch_storage
        file_id = request_json["input_file_id"]
        try:
            await storage.get_file(file_id)
        except FileNotFoundError:
            return JSONResponse(
                status_code=404, content={"error": f"File {file_id} not found"}
            )

        batch_processor: BatchProcessor = app.state.batch_processor
        batch = await batch_processor.create_batch(
            input_file_id=file_id,
            endpoint=request_json["endpoint"],
            completion_window=request_json.get("completion_window", "5s"),
            metadata=request_json.get("metadata", None),
        )

        # Return metadata as attribute, not a callable.
        return JSONResponse(content=batch.to_dict())

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to process batch request: {str(e)}"},
        )


@app.get("/v1/batches/{batch_id}")
async def route_get_batch(batch_id: str):
    try:
        batch_processor: BatchProcessor = app.state.batch_processor
        batch = await batch_processor.retrieve_batch(batch_id)
        return JSONResponse(content=batch.to_dict())
    except FileNotFoundError:
        return JSONResponse(
            status_code=404, content={"error": f"Batch {batch_id} not found"}
        )


@app.get("/v1/batches")
async def route_list_batches(limit: int = 20, after: str = None):
    try:
        batch_processor: BatchProcessor = app.state.batch_processor
        batches = await batch_processor.list_batches(limit=limit, after=after)

        # Convert batches to response format
        batch_data = [batch.to_dict() for batch in batches]

        response = {
            "object": "list",
            "data": batch_data,
            "first_id": batch_data[0]["id"] if batch_data else None,
            "last_id": batch_data[-1]["id"] if batch_data else None,
            "has_more": len(batch_data)
            == limit,  # If we got limit items, there may be more
        }

        return JSONResponse(content=response)
    except FileNotFoundError:
        return JSONResponse(status_code=404, content={"error": "No batches found"})


@app.delete("/v1/batches/{batch_id}")
async def route_cancel_batch(batch_id: str):
    try:
        batch_processor: BatchProcessor = app.state.batch_processor
        batch = await batch_processor.cancel_batch(batch_id)
        return JSONResponse(content=batch.to_dict())
    except FileNotFoundError:
        return JSONResponse(
            status_code=404, content={"error": f"Batch {batch_id} not found"}
        )


@app.post("/v1/batches")
async def route_batches(request: Request):
    """Handle batch requests that process files with specified endpoints."""
    try:
        request_json = await request.json()

        # Validate required fields
        if "input_file_id" not in request_json:
            return JSONResponse(
                status_code=400,
                content={"error": "Missing required parameter 'input_file_id'"},
            )
        if "endpoint" not in request_json:
            return JSONResponse(
                status_code=400,
                content={"error": "Missing required parameter 'endpoint'"},
            )

        # Verify file exists
        storage: Storage = app.state.batch_storage
        file_id = request_json["input_file_id"]
        try:
            await storage.get_file(file_id)
        except FileNotFoundError:
            return JSONResponse(
                status_code=404, content={"error": f"File {file_id} not found"}
            )

        batch_processor: BatchProcessor = app.state.batch_processor
        batch = await batch_processor.create_batch(
            input_file_id=file_id,
            endpoint=request_json["endpoint"],
            completion_window=request_json.get("completion_window", "5s"),
            metadata=request_json.get("metadata", None),
        )

        # Return metadata as attribute, not a callable.
        return JSONResponse(content=batch.to_dict())

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to process batch request: {str(e)}"},
        )


@app.get("/v1/batches/{batch_id}")
async def route_get_batch(batch_id: str):
    try:
        batch_processor: BatchProcessor = app.state.batch_processor
        batch = await batch_processor.retrieve_batch(batch_id)
        return JSONResponse(content=batch.to_dict())
    except FileNotFoundError:
        return JSONResponse(
            status_code=404, content={"error": f"Batch {batch_id} not found"}
        )


@app.get("/v1/batches")
async def route_list_batches(limit: int = 20, after: str = None):
    try:
        batch_processor: BatchProcessor = app.state.batch_processor
        batches = await batch_processor.list_batches(limit=limit, after=after)

        # Convert batches to response format
        batch_data = [batch.to_dict() for batch in batches]

        response = {
            "object": "list",
            "data": batch_data,
            "first_id": batch_data[0]["id"] if batch_data else None,
            "last_id": batch_data[-1]["id"] if batch_data else None,
            "has_more": len(batch_data)
            == limit,  # If we got limit items, there may be more
        }

        return JSONResponse(content=response)
    except FileNotFoundError:
        return JSONResponse(status_code=404, content={"error": "No batches found"})


@app.delete("/v1/batches/{batch_id}")
async def route_cancel_batch(batch_id: str):
    try:
        batch_processor: BatchProcessor = app.state.batch_processor
        batch = await batch_processor.cancel_batch(batch_id)
        return JSONResponse(content=batch.to_dict())
    except FileNotFoundError:
        return JSONResponse(
            status_code=404, content={"error": f"Batch {batch_id} not found"}
        )


@app.post("/v1/chat/completions")
async def route_chat_completition(request: Request):
    return await route_general_request(request, "/v1/chat/completions")


@app.post("/v1/completions")
async def route_completition(request: Request):
    return await route_general_request(request, "/v1/completions")


@app.post("/v1/embeddings")
async def route_embeddings(request: Request):
    return await route_general_request(request, "/v1/embeddings")


@app.post("/v1/rerank")
async def route_v1_rerank(request: Request):
    return await route_general_request(request, "/v1/rerank")


@app.post("/rerank")
async def route_rerank(request: Request):
    return await route_general_request(request, "/rerank")


@app.post("/v1/score")
async def route_v1_score(request: Request):
    return await route_general_request(request, "/v1/score")


@app.post("/score")
async def route_score(request: Request):
    return await route_general_request(request, "/score")


@app.get("/version")
async def show_version():
    ver = {"version": __version__}
    return JSONResponse(content=ver)


@app.get("/v1/models")
async def show_models():
    """
    Returns a list of all models available in the stack.

    Args:
        None

    Returns:
        JSONResponse: A JSON response containing the list of models.

    Raises:
        Exception: If there is an error in retrieving the endpoint information.
    """
    endpoints = GetServiceDiscovery().get_endpoint_info()
    existing_models = set()
    model_cards = []
    for endpoint in endpoints:
        if endpoint.model_name in existing_models:
            continue
        model_card = ModelCard(
            id=endpoint.model_name,
            object="model",
            created=endpoint.added_timestamp,
            owned_by="vllm",
        )
        model_cards.append(model_card)
        existing_models.add(endpoint.model_name)
    model_list = ModelList(data=model_cards)
    return JSONResponse(content=model_list.model_dump())


@app.get("/health")
async def health() -> Response:
    """
    Endpoint to check the health status of various components.

    This function verifies the health of the service discovery module and
    the engine stats scraper. If either component is down, it returns a
    503 response with the appropriate status message. If both components
    are healthy, it returns a 200 OK response.

    Returns:
        Response: A JSONResponse with status code 503 if a component is
        down, or a plain Response with status code 200 if all components
        are healthy.
    """

    if not GetServiceDiscovery().get_health():
        return JSONResponse(
            content={"status": "Service discovery module is down."}, status_code=503
        )
    if not GetEngineStatsScraper().get_health():
        return JSONResponse(
            content={"status": "Engine stats scraper is down."}, status_code=503
        )
    return Response(status_code=200)


# --- Prometheus Metrics Endpoint ---
@app.get("/metrics")
async def metrics():
    # Retrieve request stats from the monitor.
    """
    Endpoint to expose Prometheus metrics for the vLLM router.

    This function gathers request statistics, engine metrics, and health status
    of the service endpoints to update Prometheus gauges. It exports metrics
    such as queries per second (QPS), average decoding length, number of prefill
    and decoding requests, average latency, average inter-token latency, number
    of swapped requests, and the number of healthy pods for each server. The
    metrics are used to monitor the performance and health of the vLLM router
    services.

    Returns:
        Response: A HTTP response containing the latest Prometheus metrics in
        the appropriate content type.
    """

    stats = GetRequestStatsMonitor().get_request_stats(time.time())
    for server, stat in stats.items():
        current_qps.labels(server=server).set(stat.qps)
        # Assuming stat contains the following attributes:
        avg_decoding_length.labels(server=server).set(stat.avg_decoding_length)
        num_prefill_requests.labels(server=server).set(stat.in_prefill_requests)
        num_decoding_requests.labels(server=server).set(stat.in_decoding_requests)
        num_requests_running.labels(server=server).set(
            stat.in_prefill_requests + stat.in_decoding_requests
        )
        avg_latency.labels(server=server).set(stat.avg_latency)
        avg_itl.labels(server=server).set(stat.avg_itl)
        num_requests_swapped.labels(server=server).set(stat.num_swapped_requests)
    # For healthy pods, we use a hypothetical function from service discovery.
    healthy = {}
    endpoints = GetServiceDiscovery().get_endpoint_info()
    for ep in endpoints:
        # Assume each endpoint object has an attribute 'healthy' (1 if healthy, 0 otherwise).
        healthy[ep.url] = 1 if getattr(ep, "healthy", True) else 0
    for server, value in healthy.items():
        healthy_pods_total.labels(server=server).set(value)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# --- Argument Parsing and Initialization ---
def validate_args(args):
    if args.service_discovery == "static":
        if args.static_backends is None:
            raise ValueError(
                "Static backends must be provided when using static service discovery."
            )
        if args.static_models is None:
            raise ValueError(
                "Static models must be provided when using static service discovery."
            )
    if args.service_discovery == "k8s" and args.k8s_port is None:
        raise ValueError("K8s port must be provided when using K8s service discovery.")
    if args.routing_logic == "session" and args.session_key is None:
        raise ValueError(
            "Session key must be provided when using session routing logic."
        )
    if args.log_stats and args.log_stats_interval <= 0:
        raise ValueError("Log stats interval must be greater than 0.")
    if args.engine_stats_interval <= 0:
        raise ValueError("Engine stats interval must be greater than 0.")
    if args.request_stats_window <= 0:
        raise ValueError("Request stats window must be greater than 0.")


def parse_args():
    parser = argparse.ArgumentParser(description="Run the FastAPI app.")
    parser.add_argument(
        "--host", default="0.0.0.0", help="The host to run the server on."
    )
    parser.add_argument(
        "--port", type=int, default=8001, help="The port to run the server on."
    )
    parser.add_argument(
        "--service-discovery",
        required=True,
        choices=["static", "k8s"],
        help="The service discovery type.",
    )
    parser.add_argument(
        "--static-backends",
        type=str,
        default=None,
        help="The URLs of static backends, separated by commas. E.g., http://localhost:8000,http://localhost:8001",
    )
    parser.add_argument(
        "--static-models",
        type=str,
        default=None,
        help="The models of static backends, separated by commas. E.g., model1,model2",
    )
    parser.add_argument(
        "--k8s-port",
        type=int,
        default=8000,
        help="The port of vLLM processes when using K8s service discovery.",
    )
    parser.add_argument(
        "--k8s-namespace",
        type=str,
        default="default",
        help="The namespace of vLLM pods when using K8s service discovery.",
    )
    parser.add_argument(
        "--k8s-label-selector",
        type=str,
        default="",
        help="The label selector to filter vLLM pods when using K8s service discovery.",
    )
    parser.add_argument(
        "--routing-logic",
        type=str,
        required=True,
        choices=["roundrobin", "session"],
        help="The routing logic to use",
    )
    parser.add_argument(
        "--session-key",
        type=str,
        default=None,
        help="The key (in the header) to identify a session.",
    )

    # Batch API
    # TODO(gaocegege): Make these batch api related arguments to a separate config.
    parser.add_argument(
        "--enable-batch-api",
        action="store_true",
        help="Enable the batch API for processing files.",
    )
    parser.add_argument(
        "--file-storage-class",
        type=str,
        default="local_file",
        choices=["local_file"],
        help="The file storage class to use.",
    )
    parser.add_argument(
        "--file-storage-path",
        type=str,
        default="/tmp/vllm_files",
        help="The path to store files.",
    )
    parser.add_argument(
        "--batch-processor",
        type=str,
        default="local",
        choices=["local"],
        help="The batch processor to use.",
    )

    # Monitoring
    parser.add_argument(
        "--engine-stats-interval",
        type=int,
        default=30,
        help="The interval in seconds to scrape engine statistics.",
    )
    parser.add_argument(
        "--request-stats-window",
        type=int,
        default=60,
        help="The sliding window in seconds to compute request statistics.",
    )
    parser.add_argument(
        "--log-stats", action="store_true", help="Log statistics periodically."
    )
    parser.add_argument(
        "--log-stats-interval",
        type=int,
        default=10,
        help="The interval in seconds to log statistics.",
    )

    # Add --version argument
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show version and exit",
    )

    args = parser.parse_args()
    validate_args(args)
    return args


def parse_static_urls(args):
    urls = args.static_backends.split(",")
    backend_urls = []
    for url in urls:
        if validate_url(url):
            backend_urls.append(url)
        else:
            logger.warning(f"Skipping invalid URL: {url}")
    return backend_urls


def parse_static_model_names(args):
    models = args.static_models.split(",")
    return models


def InitializeAll(args):
    """
    Initialize all the components of the router with the given arguments.

    Args:
        args: the parsed command-line arguments

    Raises:
        ValueError: if the service discovery type is invalid
    """
    if args.service_discovery == "static":
        InitializeServiceDiscovery(
            ServiceDiscoveryType.STATIC,
            urls=parse_static_urls(args),
            models=parse_static_model_names(args),
        )
    elif args.service_discovery == "k8s":
        InitializeServiceDiscovery(
            ServiceDiscoveryType.K8S,
            namespace=args.k8s_namespace,
            port=args.k8s_port,
            label_selector=args.k8s_label_selector,
        )
    else:
        raise ValueError(f"Invalid service discovery type: {args.service_discovery}")

    # Initialize singletons via custom functions.
    InitializeEngineStatsScraper(args.engine_stats_interval)
    InitializeRequestStatsMonitor(args.request_stats_window)

    if args.enable_batch_api:
        logger.info("Initializing batch API")
        app.state.batch_storage = initialize_storage(
            args.file_storage_class, args.file_storage_path
        )
        app.state.batch_processor = initialize_batch_processor(
            args.batch_processor, args.file_storage_path, app.state.batch_storage
        )

    InitializeRoutingLogic(args.routing_logic, session_key=args.session_key)

    # --- Hybrid addition: attach singletons to FastAPI state ---
    app.state.engine_stats_scraper = GetEngineStatsScraper()
    app.state.request_stats_monitor = GetRequestStatsMonitor()
    app.state.router = GetRoutingLogic()


def log_stats(interval: int = 10):
    """
    Periodically logs the engine and request statistics for each service endpoint.

    This function retrieves the current service endpoints and their corresponding
    engine and request statistics, and logs them at a specified interval. The
    statistics include the number of running and queued requests, GPU cache hit
    rate, queries per second (QPS), average latency, average inter-token latency
    (ITL), and more. These statistics are also updated in the Prometheus metrics.

    Args:
        interval (int): The interval in seconds at which statistics are logged.
            Default is 10 seconds.
    """

    while True:
        time.sleep(interval)
        logstr = "\n" + "=" * 50 + "\n"
        endpoints = GetServiceDiscovery().get_endpoint_info()
        engine_stats = app.state.engine_stats_scraper.get_engine_stats()
        request_stats = app.state.request_stats_monitor.get_request_stats(time.time())
        for endpoint in endpoints:
            url = endpoint.url
            logstr += f"Model: {endpoint.model_name}\n"
            logstr += f"Server: {url}\n"
            if url in engine_stats:
                es = engine_stats[url]
                logstr += (
                    f" Engine Stats: Running Requests: {es.num_running_requests}, "
                    f"Queued Requests: {es.num_queuing_requests}, "
                    f"GPU Cache Hit Rate: {es.gpu_prefix_cache_hit_rate:.2f}\n"
                )
            else:
                logstr += " Engine Stats: No stats available\n"
            if url in request_stats:
                rs = request_stats[url]
                logstr += (
                    f" Request Stats: QPS: {rs.qps:.2f}, "
                    f"Avg Latency: {rs.avg_latency}, "
                    f"Avg ITL: {rs.avg_itl}, "
                    f"Prefill Requests: {rs.in_prefill_requests}, "
                    f"Decoding Requests: {rs.in_decoding_requests}, "
                    f"Swapped Requests: {rs.num_swapped_requests}, "
                    f"Finished: {rs.finished_requests}, "
                    f"Uptime: {rs.uptime:.2f} sec\n"
                )
                current_qps.labels(server=url).set(rs.qps)
                avg_decoding_length.labels(server=url).set(rs.avg_decoding_length)
                num_prefill_requests.labels(server=url).set(rs.in_prefill_requests)
                num_decoding_requests.labels(server=url).set(rs.in_decoding_requests)
                num_requests_running.labels(server=url).set(
                    rs.in_prefill_requests + rs.in_decoding_requests
                )
                avg_latency.labels(server=url).set(rs.avg_latency)
                avg_itl.labels(server=url).set(rs.avg_itl)
                num_requests_swapped.labels(server=url).set(rs.num_swapped_requests)
            else:
                logstr += " Request Stats: No stats available\n"
            logstr += "-" * 50 + "\n"
        logstr += "=" * 50 + "\n"
        logger.info(logstr)


def main():
    args = parse_args()
    InitializeAll(args)
    if args.log_stats:
        threading.Thread(
            target=log_stats, args=(args.log_stats_interval,), daemon=True
        ).start()

    # Workaround to avoid footguns where uvicorn drops requests with too
    # many concurrent requests active.
    set_ulimit()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
