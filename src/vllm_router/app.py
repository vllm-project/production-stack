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
import logging
import threading
from contextlib import asynccontextmanager

import sentry_sdk
import uvicorn
from fastapi import FastAPI

from vllm_router.aiohttp_client import AiohttpClientWrapper
from vllm_router.dynamic_config import (
    DynamicRouterConfig,
    get_dynamic_config_watcher,
    initialize_dynamic_config_watcher,
)
from vllm_router.experimental import get_feature_gates, initialize_feature_gates
from vllm_router.parsers.parser import parse_args
from vllm_router.routers.batches_router import batches_router
from vllm_router.routers.files_router import files_router
from vllm_router.routers.main_router import main_router
from vllm_router.routers.metrics_router import metrics_router
from vllm_router.routers.routing_logic import (
    get_routing_logic,
    initialize_routing_logic,
)
from vllm_router.service_discovery import (
    ServiceDiscoveryType,
    get_service_discovery,
    initialize_service_discovery,
)
from vllm_router.services.batch_service import initialize_batch_processor
from vllm_router.services.callbacks_service.callbacks import configure_custom_callbacks
from vllm_router.services.files_service import initialize_storage
from vllm_router.services.request_service.rewriter import (
    get_request_rewriter,
)
from vllm_router.stats.engine_stats import (
    get_engine_stats_scraper,
    initialize_engine_stats_scraper,
)
from vllm_router.stats.log_stats import log_stats
from vllm_router.stats.request_stats import (
    get_request_stats_monitor,
    initialize_request_stats_monitor,
)
from vllm_router.utils import (
    parse_comma_separated_args,
    parse_static_aliases,
    parse_static_urls,
    set_ulimit,
)

try:
    # Semantic cache integration
    from vllm_router.experimental.semantic_cache import (
        enable_semantic_cache,
        initialize_semantic_cache,
        is_semantic_cache_enabled,
    )
    from vllm_router.experimental.semantic_cache_integration import (
        semantic_cache_size,
    )

    semantic_cache_available = True
except ImportError:
    semantic_cache_available = False

logger = logging.getLogger("uvicorn")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.aiohttp_client_wrapper.start()
    if hasattr(app.state, "batch_processor"):
        await app.state.batch_processor.initialize()

    service_discovery = get_service_discovery()
    if hasattr(service_discovery, "initialize_client_sessions"):
        await service_discovery.initialize_client_sessions()

    app.state.event_loop = asyncio.get_event_loop()

    yield
    await app.state.aiohttp_client_wrapper.stop()

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
    if sentry_dsn := args.sentry_dsn:
        sentry_sdk.init(
            dsn=sentry_dsn,
            send_default_pii=True,
            profile_lifecycle="trace",
            traces_sample_rate=args.sentry_traces_sample_rate,
            profile_session_sample_rate=args.sentry_profile_session_sample_rate,
        )

    if args.service_discovery == "static":
        initialize_service_discovery(
            ServiceDiscoveryType.STATIC,
            app=app,
            urls=parse_static_urls(args.static_backends),
            models=parse_comma_separated_args(args.static_models),
            aliases=(
                parse_static_aliases(args.static_aliases)
                if args.static_aliases
                else None
            ),
            model_types=(
                parse_comma_separated_args(args.static_model_types)
                if args.static_model_types
                else None
            ),
            model_labels=(
                parse_comma_separated_args(args.static_model_labels)
                if args.static_model_labels
                else None
            ),
            static_backend_health_checks=args.static_backend_health_checks,
            prefill_model_labels=args.prefill_model_labels,
            decode_model_labels=args.decode_model_labels,
        )
    elif args.service_discovery == "k8s":
        initialize_service_discovery(
            ServiceDiscoveryType.K8S,
            k8s_service_discovery_type=args.k8s_service_discovery_type,
            app=app,
            namespace=args.k8s_namespace,
            port=args.k8s_port,
            label_selector=args.k8s_label_selector,
            prefill_model_labels=args.prefill_model_labels,
            decode_model_labels=args.decode_model_labels,
            watcher_timeout_seconds=args.k8s_watcher_timeout_seconds,
            health_check_timeout_seconds=args.backend_health_check_timeout_seconds,
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

    # Initialize dynamic config watcher
    if args.dynamic_config_yaml or args.dynamic_config_json:
        init_config = DynamicRouterConfig.from_args(args)
        if args.dynamic_config_yaml:
            initialize_dynamic_config_watcher(
                args.dynamic_config_yaml, "YAML", 10, init_config, app
            )
        elif args.dynamic_config_json:
            initialize_dynamic_config_watcher(
                args.dynamic_config_json, "JSON", 10, init_config, app
            )

    if args.callbacks:
        configure_custom_callbacks(args.callbacks, app)

    initialize_routing_logic(
        args.routing_logic,
        session_key=args.session_key,
        lmcache_controller_port=args.lmcache_controller_port,
        prefill_model_labels=args.prefill_model_labels,
        decode_model_labels=args.decode_model_labels,
        kv_aware_threshold=args.kv_aware_threshold,
    )

    # Initialize feature gates
    initialize_feature_gates(args.feature_gates)
    # Check if the SemanticCache feature gate is enabled
    feature_gates = get_feature_gates()
    if semantic_cache_available:
        if feature_gates.is_enabled("SemanticCache"):
            # The feature gate is enabled, explicitly enable the semantic cache
            enable_semantic_cache()

            # Verify that the semantic cache was successfully enabled
            if not is_semantic_cache_enabled():
                logger.error("Failed to enable semantic cache feature")

            logger.info("SemanticCache feature gate is enabled")

            # Initialize the semantic cache with the model if specified
            if args.semantic_cache_model:
                logger.info(
                    f"Initializing semantic cache with model: {args.semantic_cache_model}"
                )
                logger.info(
                    f"Semantic cache directory: {args.semantic_cache_dir or 'default'}"
                )
                logger.info(
                    f"Semantic cache threshold: {args.semantic_cache_threshold}"
                )

                cache = initialize_semantic_cache(
                    embedding_model=args.semantic_cache_model,
                    cache_dir=args.semantic_cache_dir,
                    default_similarity_threshold=args.semantic_cache_threshold,
                )

                # Update cache size metric
                if cache and hasattr(cache, "db") and hasattr(cache.db, "index"):
                    semantic_cache_size.labels(server="router").set(
                        cache.db.index.ntotal
                    )
                    logger.info(
                        f"Semantic cache initialized with {cache.db.index.ntotal} entries"
                    )

                logger.info(
                    f"Semantic cache initialized with model {args.semantic_cache_model}"
                )
            else:
                logger.warning(
                    "SemanticCache feature gate is enabled but no embedding model specified. "
                    "The semantic cache will not be functional without an embedding model. "
                    "Use --semantic-cache-model to specify an embedding model."
                )
        elif args.semantic_cache_model:
            logger.warning(
                "Semantic cache model specified but SemanticCache feature gate is not enabled. "
                "Enable the feature gate with --feature-gates=SemanticCache=true"
            )

    # --- Hybrid addition: attach singletons to FastAPI state ---
    app.state.engine_stats_scraper = get_engine_stats_scraper()
    app.state.request_stats_monitor = get_request_stats_monitor()
    app.state.router = get_routing_logic()
    app.state.request_rewriter = get_request_rewriter()


app = FastAPI(lifespan=lifespan)
app.include_router(main_router)
app.include_router(files_router)
app.include_router(batches_router)
app.include_router(metrics_router)
app.state.aiohttp_client_wrapper = AiohttpClientWrapper()
app.state.semantic_cache_available = semantic_cache_available


def main():
    args = parse_args()
    initialize_all(app, args)
    if args.log_stats:
        threading.Thread(
            target=log_stats,
            args=(
                app,
                args.log_stats_interval,
            ),
            daemon=True,
        ).start()

    # Workaround to avoid footguns where uvicorn drops requests with too
    # many concurrent requests active.
    set_ulimit()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
