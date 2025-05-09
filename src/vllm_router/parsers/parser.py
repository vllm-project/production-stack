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
import argparse
import json
import logging
import sys

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


logger = logging.getLogger(__name__)


def verify_required_args_provided(args: argparse.Namespace) -> None:
    if not args.routing_logic:
        logger.error("--routing-logic must be provided.")
        sys.exit(1)
    if not args.service_discovery:
        logger.error("--service-discovery must be provided.")
        sys.exit(1)


def load_initial_config_from_config_json_if_required(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> argparse.Namespace:
    if dynamic_config := args.dynamic_config_json:
        logger.info(f"Initial loading of dynamic config file at {dynamic_config}")
        with open(dynamic_config, encoding="utf-8") as f:
            parser.set_defaults(**json.load(f))
            args = parser.parse_args()
    return args


# --- Argument Parsing and Initialization ---
def validate_args(args):
    verify_required_args_provided(args)
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
        "--host", type=str, default="0.0.0.0", help="The host to run the server on."
    )
    parser.add_argument(
        "--port", type=int, default=8001, help="The port to run the server on."
    )
    parser.add_argument(
        "--service-discovery",
        type=str,
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
        choices=["roundrobin", "session", "kvaware"],
        help="The routing logic to use",
    )
    parser.add_argument(
        "--lmcache-controller-port",
        type=int,
        default=9000,
        help="The port of the LMCache controller.",
    )
    parser.add_argument(
        "--session-key",
        type=str,
        default=None,
        help="The key (in the header) to identify a session.",
    )
    parser.add_argument(
        "--callbacks",
        type=str,
        default=None,
        help="Path to the callback instance extending CustomCallbackHandler. Consists of <file path without .py ending>.<instance variable name>.",
    )

    # Request rewriter arguments
    parser.add_argument(
        "--request-rewriter",
        type=str,
        default="noop",
        choices=["noop"],
        help="The request rewriter to use. Default is 'noop' (no rewriting).",
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

    parser.add_argument(
        "--dynamic-config-json",
        type=str,
        default=None,
        help="The path to the json file containing the dynamic configuration.",
    )

    # Add --version argument
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show version and exit",
    )

    if semantic_cache_available:
        add_semantic_cache_args(parser)

    # Add feature gates argument
    parser.add_argument(
        "--feature-gates",
        type=str,
        default="",
        help="Comma-separated list of feature gates (e.g., 'SemanticCache=true')",
    )

    # Add log level argument
    parser.add_argument(
        "--log-level",
        type=str,
        default="info",
        choices=["critical", "error", "warning", "info", "debug", "trace"],
        help="Log level for uvicorn. Default is 'info'.",
    )

    parser.add_argument(
        "--sentry-dsn",
        type=str,
        help="Enables Sentry Error Reporting to the specified Data Source Name",
    )

    args = parser.parse_args()
    args = load_initial_config_from_config_json_if_required(parser, args)

    validate_args(args)
    return args
