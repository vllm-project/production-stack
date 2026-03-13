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

"""
Tests for dynamic config watcher recovery behavior.

Covers:
- Recovery after invalid JSON config (issue #659)
- Recovery after partial reconfiguration failure
- Normal config change detection
"""

import json
import os
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from vllm_router.dynamic_config import (
    DynamicConfigWatcher,
    DynamicRouterConfig,
)
from vllm_router.utils import SingletonMeta


def _reset_singleton():
    """Reset the DynamicConfigWatcher singleton for test isolation."""
    if DynamicConfigWatcher in SingletonMeta._instances:
        del SingletonMeta._instances[DynamicConfigWatcher]


def _make_config(routing_logic="roundrobin", **kwargs):
    """Create a minimal DynamicRouterConfig for testing."""
    return DynamicRouterConfig(
        service_discovery="static",
        routing_logic=routing_logic,
        static_backends="http://localhost:8001",
        static_models="test-model",
        **kwargs,
    )


def _write_config(path, config_dict):
    """Write a config dict as JSON to a file."""
    with open(path, "w") as f:
        json.dump(config_dict, f)


def _write_invalid_json(path):
    """Write invalid JSON to a file."""
    with open(path, "w") as f:
        f.write('{"service_discovery": "static" "routing_logic": "roundrobin"}')


class TestDynamicConfigWatcherRecovery(unittest.TestCase):
    """Tests for DynamicConfigWatcher recovery after errors."""

    def setUp(self):
        _reset_singleton()
        self.tmpdir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.tmpdir, "config.json")
        self.app = MagicMock()
        self.app.state = MagicMock()

        self.initial_config_dict = {
            "service_discovery": "static",
            "routing_logic": "roundrobin",
            "static_backends": "http://localhost:8001",
            "static_models": "test-model",
        }
        _write_config(self.config_path, self.initial_config_dict)
        self.initial_config = DynamicRouterConfig(**self.initial_config_dict)

    def tearDown(self):
        if hasattr(self, "watcher") and self.watcher is not None:
            self.watcher.close()
        _reset_singleton()
        if os.path.exists(self.config_path):
            os.remove(self.config_path)

    @patch.object(DynamicConfigWatcher, "reconfigure_all")
    def test_recovery_after_invalid_json(self, mock_reconfigure_all):
        """
        Test that after an invalid JSON config is fixed back to the same
        valid config, the system still triggers reconfiguration.
        This is the core scenario from issue #659.
        """
        # Start watcher with a short interval
        self.watcher = DynamicConfigWatcher(
            config_path=self.config_path,
            config_file_type="JSON",
            watch_interval=1,
            init_config=self.initial_config,
            app=self.app,
        )

        # Wait for initial watch cycle (no change expected)
        time.sleep(1.5)
        mock_reconfigure_all.assert_not_called()

        # Step 1: Break the config with invalid JSON
        _write_invalid_json(self.config_path)
        time.sleep(1.5)

        # Reconfigure should NOT have been called (parse error)
        mock_reconfigure_all.assert_not_called()

        # The force_reconfigure flag should be set
        self.assertTrue(self.watcher._force_reconfigure)

        # Step 2: Fix the config back to valid (same content as initial)
        _write_config(self.config_path, self.initial_config_dict)
        time.sleep(1.5)

        # Reconfigure SHOULD have been called despite config being identical
        # to current_config, because _force_reconfigure was set
        mock_reconfigure_all.assert_called_once()

    @patch.object(DynamicConfigWatcher, "reconfigure_all")
    def test_normal_config_change_detection(self, mock_reconfigure_all):
        """Test that normal config changes are detected and applied."""
        self.watcher = DynamicConfigWatcher(
            config_path=self.config_path,
            config_file_type="JSON",
            watch_interval=1,
            init_config=self.initial_config,
            app=self.app,
        )

        # Change config to a different routing logic
        new_config_dict = {**self.initial_config_dict, "routing_logic": "session"}
        _write_config(self.config_path, new_config_dict)
        time.sleep(1.5)

        # Reconfigure should have been called
        mock_reconfigure_all.assert_called_once()

    @patch.object(DynamicConfigWatcher, "reconfigure_all")
    def test_force_reconfigure_after_reconfigure_failure(
        self, mock_reconfigure_all
    ):
        """
        Test that after reconfigure_all fails, the system retries
        on the next iteration even if config hasn't changed.
        """
        # Make reconfigure_all fail on first call, succeed on second
        mock_reconfigure_all.side_effect = [
            RuntimeError("Simulated reconfigure failure"),
            None,
        ]

        self.watcher = DynamicConfigWatcher(
            config_path=self.config_path,
            config_file_type="JSON",
            watch_interval=1,
            init_config=self.initial_config,
            app=self.app,
        )

        # Change config to trigger reconfiguration
        new_config_dict = {**self.initial_config_dict, "routing_logic": "session"}
        _write_config(self.config_path, new_config_dict)
        time.sleep(1.5)

        # First call should have failed
        self.assertEqual(mock_reconfigure_all.call_count, 1)
        self.assertTrue(self.watcher._force_reconfigure)

        # Wait for retry
        time.sleep(1.5)

        # Second call should have succeeded via force retry
        self.assertEqual(mock_reconfigure_all.call_count, 2)
        self.assertFalse(self.watcher._force_reconfigure)


class TestReconfigureAllRobustness(unittest.TestCase):
    """Tests for reconfigure_all partial failure handling."""

    def setUp(self):
        _reset_singleton()
        self.app = MagicMock()
        self.app.state = MagicMock()
        self.config = _make_config()

    def tearDown(self):
        if hasattr(self, "watcher") and self.watcher is not None:
            self.watcher.close()
        _reset_singleton()

    def test_partial_failure_continues_other_subsystems(self):
        """
        Test that if one subsystem fails in reconfigure_all,
        the other subsystems are still reconfigured.
        """
        tmpdir = tempfile.mkdtemp()
        config_path = os.path.join(tmpdir, "config.json")
        _write_config(config_path, {
            "service_discovery": "static",
            "routing_logic": "roundrobin",
            "static_backends": "http://localhost:8001",
            "static_models": "test-model",
        })

        self.watcher = DynamicConfigWatcher(
            config_path=config_path,
            config_file_type="JSON",
            watch_interval=60,  # long interval, we'll call manually
            init_config=self.config,
            app=self.app,
        )

        # Mock individual reconfigure methods
        self.watcher.reconfigure_service_discovery = MagicMock(
            side_effect=ValueError("SD failed")
        )
        self.watcher.reconfigure_routing_logic = MagicMock()
        self.watcher.reconfigure_batch_api = MagicMock()
        self.watcher.reconfigure_stats = MagicMock()
        self.watcher.reconfigure_callbacks = MagicMock()

        # reconfigure_all should raise but all subsystems should be attempted
        with self.assertRaises(RuntimeError):
            self.watcher.reconfigure_all(self.config)

        # Service discovery failed, but others should have been called
        self.watcher.reconfigure_service_discovery.assert_called_once()
        self.watcher.reconfigure_routing_logic.assert_called_once()
        self.watcher.reconfigure_batch_api.assert_called_once()
        self.watcher.reconfigure_stats.assert_called_once()
        self.watcher.reconfigure_callbacks.assert_called_once()

        # Cleanup
        os.remove(config_path)


if __name__ == "__main__":
    unittest.main()
