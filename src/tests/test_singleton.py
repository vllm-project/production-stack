# test_singleton.py
import unittest

# Import the classes and helper functions from your module.
from vllm_router.stats.request_stats import (
    RequestStatsMonitor,
    SingletonMeta,
    get_request_stats_monitor,
    initialize_request_stats_monitor,
)


class TestRequestStatsMonitorSingleton(unittest.TestCase):
    def setUp(self):
        # Clear any existing singleton instance for RequestStatsMonitor
        if RequestStatsMonitor in SingletonMeta._instances:
            del SingletonMeta._instances[RequestStatsMonitor]

    def test_singleton_initialization(self):
        sliding_window = 10.0
        # First initialization using the helper.
        monitor1 = initialize_request_stats_monitor(sliding_window)
        # Subsequent retrieval using GetRequestStatsMonitor() should return the same instance.
        monitor2 = get_request_stats_monitor()
        self.assertIs(
            monitor1,
            monitor2,
            "GetRequestStatsMonitor should return the initialized singleton.",
        )

        # Directly calling the constructor with the same parameter should also return the same instance.
        monitor3 = RequestStatsMonitor(sliding_window)
        self.assertIs(
            monitor1,
            monitor3,
            "Direct constructor calls should return the same singleton instance.",
        )

    def test_initialization_without_parameter_after_initialized(self):
        sliding_window = 10.0
        # First, initialize with the sliding_window.
        monitor1 = initialize_request_stats_monitor(sliding_window)
        # Now, calling the constructor without a parameter should not raise an error
        # and should return the already initialized instance.
        monitor2 = RequestStatsMonitor()
        self.assertIs(
            monitor1,
            monitor2,
            "Calling RequestStatsMonitor() without parameter after initialization should return the singleton.",
        )

    def test_initialization_without_parameter_before_initialized(self):
        # Ensure no instance is present.
        if RequestStatsMonitor in SingletonMeta._instances:
            del SingletonMeta._instances[RequestStatsMonitor]
        # Calling the constructor without the sliding_window parameter before initialization should raise a ValueError.
        with self.assertRaises(ValueError):
            RequestStatsMonitor()  # This should fail because sliding_window_size is required on first init.


if __name__ == "__main__":
    unittest.main()
