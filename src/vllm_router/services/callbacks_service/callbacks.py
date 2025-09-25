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
import importlib

from fastapi import FastAPI

from vllm_router.log import init_logger

logger = init_logger(__name__)


def configure_custom_callbacks(callbacks_file_location: str, app: FastAPI):
    # Split the path by dots to separate module from instance
    parts = callbacks_file_location.split(".")

    # The module path is all but the last part, and the instance_name is the last part
    module_name = ".".join(parts[:-1])
    instance_name = parts[-1]

    module = importlib.import_module(module_name)
    app.state.callbacks = getattr(module, instance_name)
