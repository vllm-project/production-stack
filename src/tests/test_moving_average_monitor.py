import math
import random

import pytest

from vllm_router.stats.request_stats import MovingAverageMonitor

WINDOW = 5.0


class BruteForceWindow:
    """Recomputes every accessor from the raw window, as the router used to."""

    def __init__(self, window):
        self.window = window
        self.points = []

    def expire(self, timestamp):
        # Expiry pops from the front only, so a late, older timestamp stays
        # until everything queued before it has expired.
        while self.points and self.points[0][0] < timestamp - self.window:
            self.points.pop(0)

    def values(self):
        return [value for _, value in self.points]


def assert_matches(monitor, reference):
    values = reference.values()
    assert list(monitor.timestamps) == [t for t, _ in reference.points]
    assert list(monitor.values) == values
    if not values:
        # An empty window reports exactly 0 and -1, not a float residue.
        assert monitor.get_sum() == 0
        assert monitor.get_average() == -1
        return
    want_sum = sum(values)
    got_sum = monitor.get_sum()
    if all(isinstance(value, int) for value in values):
        # Request counts (QPS) must stay exact integers.
        assert got_sum == want_sum and isinstance(got_sum, int)
    assert math.isclose(got_sum, want_sum, rel_tol=1e-9, abs_tol=1e-9)
    assert math.isclose(
        monitor.get_average(), want_sum / len(values), rel_tol=1e-9, abs_tol=1e-9
    )


def drive(seed, steps, int_values):
    rng = random.Random(seed)
    monitor = MovingAverageMonitor(WINDOW)
    reference = BruteForceWindow(WINDOW)
    assert_matches(monitor, reference)
    now = 0.0
    for _ in range(steps):
        roll = rng.random()
        if roll < 0.15:
            pass  # burst: same timestamp as the previous call
        elif roll < 0.20:
            now += rng.uniform(WINDOW, 3 * WINDOW)  # idle gap empties the window
        elif roll < 0.25:
            now -= rng.uniform(0, 1)  # late caller with an older timestamp
        else:
            now += rng.expovariate(10)
        if rng.random() < 0.3:
            monitor.update_no_value(now)
        else:
            value = 1 if int_values else rng.uniform(0, 100)
            monitor.update(now, value)
            reference.points.append((now, value))
        reference.expire(now)
        assert_matches(monitor, reference)


@pytest.mark.parametrize("seed", range(20))
def test_float_values_match_brute_force(seed):
    drive(seed, 2000, int_values=False)


@pytest.mark.parametrize("seed", range(5))
def test_request_counts_match_brute_force_exactly(seed):
    drive(seed, 2000, int_values=True)


def test_sum_is_exact_again_once_the_window_has_turned_over():
    # Huge values leave the window while fewer of them have expired than the
    # window still holds, so the running sum may be off for a while; once the
    # window has turned over it must equal a fresh sum of what is left.
    rng = random.Random(0)
    monitor = MovingAverageMonitor(WINDOW)
    for _ in range(999):
        monitor.update(0.0, rng.uniform(1e9, 2e9))
    for _ in range(1000):
        monitor.update(WINDOW, rng.uniform(0, 1))
    monitor.update_no_value(WINDOW + 0.5)  # the huge values expire
    for i in range(1000):
        monitor.update(WINDOW + 1 + i * 0.004, rng.uniform(0, 1))
    monitor.update_no_value(2 * WINDOW + 0.5)  # the first small batch expires
    assert len(monitor.values) == 1000 and min(monitor.timestamps) > WINDOW
    assert monitor.get_sum() == sum(monitor.values)
    assert monitor.get_average() == sum(monitor.values) / len(monitor.values)


def test_hour_long_outlier_leaving_the_window_keeps_the_sum_close():
    # Realistic magnitudes: latencies of 50 ms to 5 s and one request that took
    # an hour. Its expiry does not trigger a re-sum, so this checks the error
    # left by the subtraction stays far below anything the router acts on.
    rng = random.Random(1)
    monitor = MovingAverageMonitor(WINDOW)
    monitor.update(0.0, 3600.0)
    latencies = [rng.uniform(0.05, 5.0) for _ in range(1000)]
    for value in latencies:
        monitor.update(WINDOW, value)
    monitor.update_no_value(WINDOW + 0.5)
    assert list(monitor.values) == latencies
    assert math.isclose(monitor.get_sum(), sum(latencies), rel_tol=1e-12)
    assert math.isclose(monitor.get_average(), sum(latencies) / 1000, rel_tol=1e-12)


def test_empty_monitor_and_boundary():
    monitor = MovingAverageMonitor(WINDOW)
    assert monitor.get_sum() == 0
    assert monitor.get_average() == -1
    monitor.update(10.0, 2.0)
    monitor.update(10.0, 4.0)
    # A point exactly one window old is still inside the window.
    monitor.update_no_value(10.0 + WINDOW)
    assert monitor.get_sum() == 6.0
    assert monitor.get_average() == 3.0
    monitor.update_no_value(10.0 + WINDOW + 1e-6)
    assert monitor.get_sum() == 0
    assert monitor.get_average() == -1
