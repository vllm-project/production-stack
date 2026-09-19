"""Unit tests for the retry configuration itself: status classification,
backoff maths, validation, and construction from CLI arguments."""

from argparse import Namespace

import pytest

from vllm_router.services.request_service.retry import (
    RETRIES_DISABLED,
    RETRYABLE_STATUS_CODES,
    RetryConfig,
    is_retryable_status,
)


class TestIsRetryableStatus:
    @pytest.mark.parametrize("status", sorted(RETRYABLE_STATUS_CODES))
    def test_retryable(self, status):
        assert is_retryable_status(status)

    @pytest.mark.parametrize(
        "status", [200, 201, 204, 400, 401, 403, 404, 405, 409, 422, 499, 501]
    )
    def test_not_retryable(self, status):
        assert not is_retryable_status(status)

    def test_documented_set(self):
        """The set is part of the CLI contract, so pin it explicitly."""
        assert RETRYABLE_STATUS_CODES == {408, 429, 500, 502, 503, 504}


class TestDefaults:
    def test_retrying_is_opt_in(self):
        """A default config must reproduce the historical single attempt."""
        config = RetryConfig()
        assert config.max_attempts == 1
        assert not config.enabled

    def test_shared_disabled_instance(self):
        assert RETRIES_DISABLED == RetryConfig()
        assert not RETRIES_DISABLED.enabled

    def test_enabled_once_more_than_one_attempt(self):
        assert RetryConfig(max_attempts=2).enabled

    def test_is_immutable(self):
        config = RetryConfig()
        with pytest.raises(Exception):
            config.max_attempts = 5


class TestBackoff:
    def test_grows_by_the_multiplier(self):
        config = RetryConfig(
            max_attempts=5,
            initial_backoff_ms=50,
            backoff_multiplier=1.5,
            jitter_factor=0.0,
        )
        assert config.backoff_seconds(0) == pytest.approx(0.05)
        assert config.backoff_seconds(1) == pytest.approx(0.075)
        assert config.backoff_seconds(2) == pytest.approx(0.1125)
        assert config.backoff_seconds(3) == pytest.approx(0.16875)

    def test_honours_a_custom_multiplier(self):
        config = RetryConfig(
            max_attempts=5,
            initial_backoff_ms=100,
            backoff_multiplier=2.0,
            jitter_factor=0.0,
        )
        assert [config.backoff_seconds(i) for i in range(4)] == pytest.approx(
            [0.1, 0.2, 0.4, 0.8]
        )

    def test_is_capped(self):
        config = RetryConfig(max_attempts=5, max_backoff_ms=100, jitter_factor=0.0)
        assert config.backoff_seconds(10) == pytest.approx(0.1)
        assert config.backoff_seconds(100) == pytest.approx(0.1)

    def test_jitter_spreads_delays_within_bounds(self):
        """Jitter is what stops a fleet retrying in lockstep."""
        config = RetryConfig(max_attempts=5, jitter_factor=0.5)
        delays = [config.backoff_seconds(0) for _ in range(200)]

        assert min(delays) < max(delays), "jitter must actually vary the delay"
        assert all(0.025 <= d <= 0.075 for d in delays), "base 50ms +/- 50%"

    def test_jitter_can_be_switched_off(self):
        config = RetryConfig(max_attempts=5, jitter_factor=0.0)
        assert len({config.backoff_seconds(0) for _ in range(20)}) == 1

    def test_delay_is_never_negative(self):
        config = RetryConfig(max_attempts=5, jitter_factor=1.0)
        assert all(config.backoff_seconds(0) >= 0.0 for _ in range(200))


class TestValidation:
    @pytest.mark.parametrize(
        "kwargs, message",
        [
            ({"max_attempts": 0}, "max attempts"),
            ({"initial_backoff_ms": 0}, "initial backoff"),
            ({"initial_backoff_ms": -1}, "initial backoff"),
            ({"initial_backoff_ms": 500, "max_backoff_ms": 100}, "max backoff"),
            ({"backoff_multiplier": 0.9}, "multiplier"),
            ({"jitter_factor": -0.1}, "jitter"),
            ({"jitter_factor": 1.1}, "jitter"),
        ],
    )
    def test_rejects_invalid(self, kwargs, message):
        with pytest.raises(ValueError, match=message):
            RetryConfig(**kwargs)

    def test_accepts_boundaries(self):
        RetryConfig(max_attempts=1, jitter_factor=0.0, backoff_multiplier=1.0)
        RetryConfig(max_attempts=2, jitter_factor=1.0)
        RetryConfig(initial_backoff_ms=50, max_backoff_ms=50)


class TestFromArgs:
    @staticmethod
    def _args(**overrides):
        args = Namespace(
            enable_retries=True,
            max_retries=5,
            initial_backoff_ms=50,
            max_backoff_ms=30000,
            backoff_multiplier=1.5,
            jitter_factor=0.2,
        )
        for key, value in overrides.items():
            setattr(args, key, value)
        return args

    def test_disabled_ignores_every_other_flag(self):
        """A config template carrying retry values must not change behaviour."""
        config = RetryConfig.from_args(
            self._args(enable_retries=False, max_retries=99, backoff_multiplier=0.1)
        )
        assert config == RetryConfig()
        assert not config.enabled

    def test_absent_flag_is_treated_as_disabled(self):
        assert RetryConfig.from_args(Namespace()) == RetryConfig()

    def test_enabled_maps_every_flag(self):
        config = RetryConfig.from_args(
            self._args(
                max_retries=10,
                initial_backoff_ms=100,
                max_backoff_ms=60000,
                backoff_multiplier=2.0,
                jitter_factor=0.1,
            )
        )
        assert config == RetryConfig(
            max_attempts=10,
            initial_backoff_ms=100,
            max_backoff_ms=60000,
            backoff_multiplier=2.0,
            jitter_factor=0.1,
        )

    def test_invalid_values_surface_as_value_error(self):
        with pytest.raises(ValueError, match="jitter"):
            RetryConfig.from_args(self._args(jitter_factor=5.0))
