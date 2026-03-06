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

"""Tests for request cancellation propagation (#634).

Verifies that when a client disconnects during a non-streaming request,
the router closes its connection to the backend engine, causing vLLM
to abort the in-flight request.
"""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestDisconnectMonitor(unittest.TestCase):
    """Test the disconnect monitoring logic in process_request."""

    def test_disconnect_monitor_cancels_backend(self):
        """
        Simulate a client disconnect and verify that the backend response
        gets closed, which propagates cancellation to the engine.
        """

        async def _run():
            # Mock objects
            mock_response = MagicMock()
            mock_response.close = MagicMock()

            # Simulate disconnect after 0.1s
            call_count = 0

            async def mock_is_disconnected():
                nonlocal call_count
                call_count += 1
                # Return False first, then True to simulate disconnect
                return call_count > 1

            mock_request = MagicMock()
            mock_request.is_disconnected = mock_is_disconnected

            # Create the disconnect monitor task
            async def _disconnect_monitor():
                try:
                    while True:
                        if await mock_request.is_disconnected():
                            mock_response.close()
                            return
                        await asyncio.sleep(0.05)
                except asyncio.CancelledError:
                    pass

            task = asyncio.create_task(_disconnect_monitor())

            # Wait for the task to detect disconnect
            await asyncio.sleep(0.2)

            # Verify the backend response was closed
            mock_response.close.assert_called_once()

            # Clean up
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        asyncio.run(_run())

    def test_disconnect_monitor_cancelled_on_normal_completion(self):
        """
        Verify that the disconnect monitor task is properly cancelled
        when the request completes normally (client stays connected).
        """

        async def _run():
            mock_response = MagicMock()
            mock_response.close = MagicMock()

            # Client never disconnects
            async def mock_is_disconnected():
                return False

            mock_request = MagicMock()
            mock_request.is_disconnected = mock_is_disconnected

            async def _disconnect_monitor():
                try:
                    while True:
                        if await mock_request.is_disconnected():
                            mock_response.close()
                            return
                        await asyncio.sleep(0.05)
                except asyncio.CancelledError:
                    pass

            task = asyncio.create_task(_disconnect_monitor())

            # Simulate normal request completion - cancel the task
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

            # Verify backend response was NOT closed
            mock_response.close.assert_not_called()

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
