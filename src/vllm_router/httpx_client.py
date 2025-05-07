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
import httpx

from vllm_router.log import init_logger

logger = init_logger(__name__)


class HTTPXClientWrapper:

    async_client = None

    def start(self):
        """Instantiate the client. Call from the FastAPI startup hook."""
        # To fully leverage the router's concurrency capabilities,
        # we set the maximum number of connections to be unlimited.
        limits = httpx.Limits(max_connections=None)
        self.async_client = httpx.AsyncClient(limits=limits)
        logger.info(f"httpx AsyncClient instantiated. Id {id(self.async_client)}")

    async def stop(self):
        """Gracefully shutdown. Call from FastAPI shutdown hook."""
        logger.info(
            f"httpx async_client.is_closed(): {self.async_client.is_closed} - Now close it. Id (will be unchanged): {id(self.async_client)}"
        )
        await self.async_client.aclose()
        logger.info(
            f"httpx async_client.is_closed(): {self.async_client.is_closed}. Id (will be unchanged): {id(self.async_client)}"
        )
        self.async_client = None
        logger.info("httpx AsyncClient closed")

    def __call__(self):
        """Calling the instantiated HTTPXClientWrapper returns the wrapped singleton."""
        # Ensure we don't use it if not started / running
        assert self.async_client is not None
        return self.async_client
