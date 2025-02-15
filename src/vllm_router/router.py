import argparse
import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse

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
from vllm_router.utils import validate_url

httpx_client_wrapper = HTTPXClientWrapper()
logger = logging.getLogger("uvicorn")

STACK_VERSION = "0.0.1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    httpx_client_wrapper.start()
    if hasattr(app.state, "batch_processor"):
        await app.state.batch_processor.initialize()
    yield
    await httpx_client_wrapper.stop()


app = FastAPI(lifespan=lifespan)

# TODO: better request id system


async def process_request(
    method, header, body, backend_url, request_id, endpoint, debug_request=None
):
    """
    Async generator to stream data from the backend server to the client.
    """
    first_token = False
    total_len = 0
    # Pass response headers to the client
    start_time = time.time()
    GetRequestStatsMonitor().on_new_request(backend_url, request_id, start_time)

    client = httpx_client_wrapper()
    async with client.stream(
        method=method,
        url=backend_url + endpoint,
        headers=dict(header),
        content=body,
        timeout=None,
    ) as backend_response:
        yield backend_response.headers, backend_response.status_code

        # Stream response content
        async for chunk in backend_response.aiter_bytes():
            total_len += len(chunk)
            if not first_token:
                first_token = True
                GetRequestStatsMonitor().on_request_response(
                    backend_url, request_id, time.time()
                )
            yield chunk

    GetRequestStatsMonitor().on_request_complete(backend_url, request_id, time.time())

    # if debug_request:
    #    logger.debug(f"Finished the request with request id: {debug_request.headers.get('x-request-id', None)} at {time.time()}")


async def route_general_request(request: Request, endpoint: str):
    """
    Route the incoming request to the backend server and stream the response
    back to the client.
    """
    in_router_time = time.time()
    request_id = str(uuid.uuid4())

    # TODO (ApostaC): merge two awaits into one
    request_body = await request.body()
    request_json = await request.json()
    requested_model = request_json.get("model", None)
    if requested_model is None:
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid request: missing 'model' in request body."},
        )

    endpoints = GetServiceDiscovery().get_endpoint_info()
    engine_stats = GetEngineStatsScraper().get_engine_stats()
    request_stats = GetRequestStatsMonitor().get_request_stats(time.time())

    endpoints = list(filter(lambda x: x.model_name == requested_model, endpoints))
    if len(endpoints) == 0:
        return JSONResponse(
            status_code=400, content={"error": f"Model {requested_model} not found."}
        )

    server_url = GetRoutingLogic().route_request(
        endpoints, engine_stats, request_stats, request
    )

    curr_time = time.time()
    logger.info(
        f"Routing request {request_id} to {server_url} at {curr_time}, "
        f"process time = {curr_time - in_router_time:.4f}"
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
    )


@app.post("/v1/files")
async def route_files(request: Request):
    """Handle file upload requests that include a purpose and file data."""
    form = await request.form()

    # Validate required fields
    if "purpose" not in form:
        # Unlike openai, we do not support fine-tuning, so we do not need to
        # check for 'purpose`.`
        purpose = "unknown"
    else:
        purpose = form["purpose"]
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


@app.post("/v1/chat/completions")
async def route_chat_completition(request: Request):
    return await route_general_request(request, "/v1/chat/completions")


@app.post("/v1/completions")
async def route_completition(request: Request):
    return await route_general_request(request, "/v1/completions")


@app.get("/version")
async def show_version():
    ver = {"version": STACK_VERSION}
    return JSONResponse(content=ver)


@app.get("/v1/models")
async def show_models():
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
    """Health check. check the health of the threads"""
    if not GetServiceDiscovery().get_health():
        return JSONResponse(
            content={"status": "Service discovery module is down."}, status_code=503
        )
    if not GetEngineStatsScraper().get_health():
        return JSONResponse(
            content={"status": "Engine stats scraper is down."}, status_code=503
        )
    return Response(status_code=200)


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

    if args.service_discovery == "static" and args.static_backends is None:
        raise ValueError(
            "Static backends must be provided when using static service discovery."
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

    # Service discovery
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
        help="The urls of static backends, separated by comma."
        "E.g., http://localhost:8000,http://localhost:8001",
    )
    parser.add_argument(
        "--static-models",
        type=str,
        default=None,
        help="The models of static backends, separated by comma. E.g., model1,model2",
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

    # Routing logic
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
        help="The sliding window seconds to compute request statistics.",
    )

    # Logging
    parser.add_argument(
        "--log-stats", action="store_true", help="Log statistics periodically."
    )

    parser.add_argument(
        "--log-stats-interval",
        type=int,
        default=10,
        help="The interval in seconds to log statistics.",
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
            logger.warning(f"Skipping invalid url: {url}")
    return backend_urls


def parse_static_model_names(args):
    models = args.static_models.split(",")
    return models


def InitializeAll(args):
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


def log_stats(interval: int = 10):
    while True:
        time.sleep(interval)
        logstr = "\n" + "=" * 50 + "\n"
        endpoints = GetServiceDiscovery().get_endpoint_info()
        engine_stats = GetEngineStatsScraper().get_engine_stats()
        request_stats = GetRequestStatsMonitor().get_request_stats(time.time())
        for endpoint in endpoints:
            url = endpoint.url
            logstr += f"Server: {url}\n"
            if url in engine_stats:
                logstr += f"  Engine stats: {engine_stats[url]}\n"
            else:
                logstr += "  Engine stats: No stats available\n"

            if url in request_stats:
                logstr += f"  Request Stats: {request_stats[url]}\n"
            else:
                logstr += "  Request Stats: No stats available\n"

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

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
