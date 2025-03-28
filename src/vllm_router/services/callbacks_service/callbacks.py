import importlib

from fastapi import FastAPI

from vllm_router.log import init_logger

logger = init_logger(__name__)


def initialize_custom_callbacks(callbacks_file_location: str, app: FastAPI):
    # Split the path by dots to separate module from instance
    parts = callbacks_file_location.split(".")

    # The module path is all but the last part, and the instance_name is the last part
    module_name = ".".join(parts[:-1])
    instance_name = parts[-1]

    module = importlib.import_module(module_name)
    app.state.callbacks = getattr(module, instance_name)
