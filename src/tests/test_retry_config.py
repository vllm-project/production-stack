from vllm_router.routers.routing_logic import RetryConfig
from vllm_router.services.request_service.request import is_retryable_status


class TestIsRetryableStatus:
    """Test retryable status code detection."""

    def test_retryable_status_codes(self):
        """Test that expected status codes are retryable."""
        assert is_retryable_status(408)
        assert is_retryable_status(429)
        assert is_retryable_status(500)
        assert is_retryable_status(502)
        assert is_retryable_status(503)
        assert is_retryable_status(504)

    def test_non_retryable_status_codes(self):
        """Test that non-retryable status codes return False."""
        assert not is_retryable_status(200)
        assert not is_retryable_status(201)
        assert not is_retryable_status(204)
        assert not is_retryable_status(400)
        assert not is_retryable_status(401)
        assert not is_retryable_status(403)
        assert not is_retryable_status(404)
        assert not is_retryable_status(405)
        assert not is_retryable_status(422)
        assert not is_retryable_status(499)


class TestRetryConfig:
    """Test retry configuration with exponential backoff."""

    def test_retry_config_defaults(self):
        """Test default retry configuration matches sglang."""
        config = RetryConfig()
        assert config.max_retries == 5
        assert config.initial_backoff_ms == 50
        assert config.max_backoff_ms == 30000
        assert config.backoff_multiplier == 1.5
        assert config.jitter_factor == 0.2

    def test_backoff_calculation_without_jitter(self):
        """Test exponential backoff calculation."""
        config = RetryConfig(jitter_factor=0.0)

        # Attempt 0: 50ms
        assert RetryConfig.calculate_delay(0, config) == 0.05

        # Attempt 1: 75ms (50 * 1.5)
        assert RetryConfig.calculate_delay(1, config) == 0.075

        # Attempt 2: 112.5ms (50 * 1.5^2)
        assert abs(RetryConfig.calculate_delay(2, config) - 0.1125) < 0.001

        # Attempt 3: 168.75ms (50 * 1.5^3)
        assert abs(RetryConfig.calculate_delay(3, config) - 0.16875) < 0.001

    def test_max_backoff_cap(self):
        """Test that backoff is capped at max_backoff_ms."""
        config = RetryConfig(max_backoff_ms=100, jitter_factor=0.0)

        # Even with high attempt number, should cap at 100ms
        assert RetryConfig.calculate_delay(10, config) == 0.1
        assert RetryConfig.calculate_delay(100, config) == 0.1

    def test_jitter_applied(self):
        """Test that jitter randomizes delay."""
        config = RetryConfig(jitter_factor=0.5)

        # Collect multiple delays to verify variation
        delays = [RetryConfig.calculate_delay(0, config) for _ in range(100)]

        # Should have variation due to jitter
        assert min(delays) < max(delays)

        # All delays should be within ±50% of base delay (50ms)
        # So range should be 25ms to 75ms (0.025s to 0.075s)
        assert all(0.025 <= d <= 0.075 for d in delays)

    def test_custom_retry_config(self):
        """Test custom retry configuration."""
        config = RetryConfig(
            max_retries=10,
            initial_backoff_ms=100,
            max_backoff_ms=60000,
            backoff_multiplier=2.0,
            jitter_factor=0.1,
        )
        assert config.max_retries == 10
        assert config.initial_backoff_ms == 100
        assert config.max_backoff_ms == 60000
        assert config.backoff_multiplier == 2.0
        assert config.jitter_factor == 0.1

    def test_backoff_multiplier_application(self):
        """Test that backoff multiplier is correctly applied."""
        config = RetryConfig(
            initial_backoff_ms=100, backoff_multiplier=2.0, jitter_factor=0.0
        )

        # With multiplier 2.0, each attempt doubles the delay
        assert RetryConfig.calculate_delay(0, config) == 0.1  # 100ms
        assert RetryConfig.calculate_delay(1, config) == 0.2  # 200ms
        assert RetryConfig.calculate_delay(2, config) == 0.4  # 400ms
        assert RetryConfig.calculate_delay(3, config) == 0.8  # 800ms
