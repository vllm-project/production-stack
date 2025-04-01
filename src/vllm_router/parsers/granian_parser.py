import argparse

from vllm_router.parsers.parser import parse_args as base_parse_args
from vllm_router.version import __version__


def parse_granian_args():
    """
    Parse command-line arguments including Granian-specific options.

    Extends the base parser with Granian specific parameters for
    Granian server configurations.

    Returns:
        argparse.Namespace: The parsed arguments
    """
    # Get the base arguments from the original parser
    args = base_parse_args()

    # Create a new parser for Granian-specific arguments
    parser = argparse.ArgumentParser(description="Run the Granian server.")

    # Add Granian-specific arguments
    parser.add_argument(
        "--granian-workers",
        type=int,
        default=4,
        help="Number of worker processes for Granian server.",
    )
    parser.add_argument(
        "--granian-threads",
        type=int,
        default=8,
        help="Number of threads per worker for Granian server.",
    )
    parser.add_argument(
        "--granian-loop",
        type=str,
        default="auto",
        choices=["auto", "asyncio", "uvloop"],
        help="Event loop implementation to use.",
    )
    parser.add_argument(
        "--granian-log-level",
        type=str,
        default="info",
        choices=["critical", "error", "warning", "info", "debug", "trace"],
        help="Log level for Granian server.",
    )

    # Parse only the known arguments, ignore the ones already parsed
    # This avoids duplicate argument errors
    granian_args, _ = parser.parse_known_args()

    # Update the base args with Granian-specific args
    for key, value in vars(granian_args).items():
        setattr(args, key, value)

    return args
