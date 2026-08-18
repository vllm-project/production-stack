import sys
import threading

from fastapi import FastAPI

from vllm_router.dynamic_config import (
    DynamicRouterConfig,
    initialize_dynamic_config_watcher,
)


def run_unclosed_watcher(config_path: str) -> int:
    initialize_dynamic_config_watcher(
        config_path,
        "JSON",
        60,
        DynamicRouterConfig.from_json(config_path),
        FastAPI(),
    )
    return 0


def run_with_invalid_app(config_path: str) -> int:
    threads_before = set(threading.enumerate())
    try:
        initialize_dynamic_config_watcher(
            config_path,
            "JSON",
            60,
            DynamicRouterConfig.from_json(config_path),
            object(),
        )
    except AssertionError:
        thread_was_started = bool(set(threading.enumerate()) - threads_before)
        return 1 if thread_was_started else 0
    return 2


def main() -> int:
    scenario, config_path = sys.argv[1:]
    if scenario == "unclosed-watcher":
        return run_unclosed_watcher(config_path)
    if scenario == "invalid-app":
        return run_with_invalid_app(config_path)
    raise ValueError(f"Unknown scenario: {scenario}")


if __name__ == "__main__":
    raise SystemExit(main())
