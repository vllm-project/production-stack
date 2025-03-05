import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from vllm_router.dynamic_config import get_dynamic_config_watcher
from vllm_router.log import init_logger
from vllm_router.protocols import ModelCard, ModelList
from vllm_router.service_discovery import get_service_discovery
from vllm_router.services.request_service.request import route_general_request
from vllm_router.stats.engine_stats import get_engine_stats_scraper
from vllm_router.version import __version__

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

main_router = APIRouter()

logger = init_logger(__name__)


@main_router.post("/v1/chat/completions")
async def route_chat_completion(request: Request):
    if semantic_cache_available:
        # Check if the request can be served from the semantic cache
        logger.debug("Received chat completion request, checking semantic cache")
        cache_response = await check_semantic_cache(request=request)

        if cache_response:
            logger.info("Serving response from semantic cache")
            return cache_response

    logger.debug("No cache hit, forwarding request to backend")
    return await route_general_request(request, "/v1/chat/completions")


@main_router.post("/v1/completions")
async def route_completion(request: Request):
    return await route_general_request(request, "/v1/completions")


@main_router.post("/v1/embeddings")
async def route_embeddings(request: Request):
    return await route_general_request(request, "/v1/embeddings")


@main_router.post("/v1/rerank")
async def route_v1_rerank(request: Request):
    return await route_general_request(request, "/v1/rerank")


@main_router.post("/rerank")
async def route_rerank(request: Request):
    return await route_general_request(request, "/rerank")


@main_router.post("/v1/score")
async def route_v1_score(request: Request):
    return await route_general_request(request, "/v1/score")


@main_router.post("/score")
async def route_score(request: Request):
    return await route_general_request(request, "/score")


@main_router.get("/version")
async def show_version():
    ver = {"version": __version__}
    return JSONResponse(content=ver)


@main_router.get("/v1/models")
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
    endpoints = get_service_discovery().get_endpoint_info()
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


@main_router.get("/health")
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

    if not get_service_discovery().get_health():
        return JSONResponse(
            content={"status": "Service discovery module is down."}, status_code=503
        )
    if not get_engine_stats_scraper().get_health():
        return JSONResponse(
            content={"status": "Engine stats scraper is down."}, status_code=503
        )

    if get_dynamic_config_watcher() is not None:
        dynamic_config = get_dynamic_config_watcher().get_current_config()
        return JSONResponse(
            content={
                "status": "healthy",
                "dynamic_config": json.loads(dynamic_config.to_json_str()),
            },
            status_code=200,
        )
    else:
        return JSONResponse(content={"status": "healthy"}, status_code=200)
