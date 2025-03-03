import logging
import threading
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from vllm_router.dynamic_config import (
    get_dynamic_config_watcher,
    DynamicRouterConfig,
    initialize_dynamic_config_watcher,
)
from vllm_router.httpx_client import HTTPXClientWrapper
from vllm_router.parsers.parser import parse_args
from vllm_router.routers.batches_router import batches_router
from vllm_router.routers.files_router import files_router
from vllm_router.routers.main_router import main_router
from vllm_router.routers.metrics_router import metrics_router
from vllm_router.routers.routing_logic import (
    initialize_routing_logic,
    get_routing_logic,
)
from vllm_router.service_discovery import (
    get_service_discovery,
    initialize_service_discovery,
    ServiceDiscoveryType,
)
from vllm_router.services.batch_service import initialize_batch_processor
from vllm_router.services.files_service import initialize_storage
from vllm_router.stats.engine_stats import (
    get_engine_stats_scraper,
    initialize_engine_stats_scraper,
)
from vllm_router.stats.log_stats import log_stats
from vllm_router.stats.request_stats import (
    initialize_request_stats_monitor,
    get_request_stats_monitor,
)
from vllm_router.utils import set_ulimit, parse_static_urls, parse_static_model_names

logger = logging.getLogger("uvicorn")


@asynccontextmanager
async def lifespan(app: FastAPI):
    httpx_client_wrapper.start()
    if hasattr(app.state, "batch_processor"):
        await app.state.batch_processor.initialize()
    yield
    await httpx_client_wrapper.stop()

    # Close the threaded-components
    logger.info("Closing engine stats scraper")
    engine_stats_scraper = get_engine_stats_scraper()
    engine_stats_scraper.close()

    logger.info("Closing service discovery module")
    service_discovery = get_service_discovery()
    service_discovery.close()

    # Close the optional dynamic config watcher
    dyn_cfg_watcher = get_dynamic_config_watcher()
    if dyn_cfg_watcher is not None:
        logger.info("Closing dynamic config watcher")
        dyn_cfg_watcher.close()


def initialize_all(app: FastAPI, args):
    """
    Initialize all the components of the router with the given arguments.

    Args:
        app (FastAPI): FastAPI application
        args: the parsed command-line arguments

    Raises:
        ValueError: if the service discovery type is invalid
    """
    if args.service_discovery == "static":
        initialize_service_discovery(
            ServiceDiscoveryType.STATIC,
            urls=parse_static_urls(args.static_backends),
            models=parse_static_model_names(args.static_models),
        )
    elif args.service_discovery == "k8s":
        initialize_service_discovery(
            ServiceDiscoveryType.K8S,
            namespace=args.k8s_namespace,
            port=args.k8s_port,
            label_selector=args.k8s_label_selector,
        )
    else:
        raise ValueError(f"Invalid service discovery type: {args.service_discovery}")

    # Initialize singletons via custom functions.
    initialize_engine_stats_scraper(args.engine_stats_interval)
    initialize_request_stats_monitor(args.request_stats_window)

    if args.enable_batch_api:
        logger.info("Initializing batch API")
        app.state.batch_storage = initialize_storage(
            args.file_storage_class, args.file_storage_path
        )
        app.state.batch_processor = initialize_batch_processor(
            args.batch_processor, args.file_storage_path, app.state.batch_storage
        )

    initialize_routing_logic(args.routing_logic, session_key=args.session_key)

    # --- Hybrid addition: attach singletons to FastAPI state ---
    app.state.engine_stats_scraper = get_engine_stats_scraper()
    app.state.request_stats_monitor = get_request_stats_monitor()
    app.state.router = get_routing_logic()

    # Initialize dynamic config watcher
    if args.dynamic_config_json:
        init_config = DynamicRouterConfig.from_args(args)
        initialize_dynamic_config_watcher(
            args.dynamic_config_json, 10, init_config, app
        )


app = FastAPI()
app.include_router(main_router)
app.include_router(files_router)
app.include_router(batches_router)
app.include_router(metrics_router)
httpx_client_wrapper = HTTPXClientWrapper()


def main():
    args = parse_args()
    initialize_all(app, args)
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
