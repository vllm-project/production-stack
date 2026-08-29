# test_request_stats_leak.py
"""
Regression tests for the request-tracking leaks fixed alongside
production-stack#707: RequestStatsMonitor.on_request_complete() previously
always decremented in_decoding_requests regardless of whether the request
ever reached decode, and never released request_start_time/first_token_time,
leaking one entry per request for the life of the process.
"""
import unittest

from vllm_router.stats.request_stats import RequestStatsMonitor, SingletonMeta


class TestOnRequestCompleteBucketRelease(unittest.TestCase):
    def setUp(self):
        if RequestStatsMonitor in SingletonMeta._instances:
            del SingletonMeta._instances[RequestStatsMonitor]
        self.monitor = RequestStatsMonitor(sliding_window_size=10.0)
        self.engine_url = "http://engine-1:8000"
        self.request_id = "req-1"

    def test_reached_decode_true_releases_decoding_bucket(self):
        self.monitor.on_new_request(self.engine_url, self.request_id, timestamp=0.0)
        self.monitor.on_request_response(
            self.engine_url, self.request_id, timestamp=0.1
        )
        self.assertEqual(self.monitor.in_prefill_requests[self.engine_url], 0)
        self.assertEqual(self.monitor.in_decoding_requests[self.engine_url], 1)

        self.monitor.on_request_complete(
            self.engine_url, self.request_id, timestamp=0.2, reached_decode=True
        )
        self.assertEqual(self.monitor.in_decoding_requests[self.engine_url], 0)
        self.assertEqual(self.monitor.in_prefill_requests[self.engine_url], 0)

    def test_reached_decode_false_releases_prefill_bucket_not_decoding(self):
        # A request that fails/disconnects before its first token never calls
        # on_request_response(), so it's still sitting in in_prefill_requests.
        self.monitor.on_new_request(self.engine_url, self.request_id, timestamp=0.0)
        self.assertEqual(self.monitor.in_prefill_requests[self.engine_url], 1)

        self.monitor.on_request_complete(
            self.engine_url, self.request_id, timestamp=0.2, reached_decode=False
        )
        self.assertEqual(self.monitor.in_prefill_requests[self.engine_url], 0)
        # in_decoding_requests was never touched for this engine -- confirms the
        # old behavior (always decrementing in_decoding_requests) would have
        # silently no-opped here (clamped at 0) while leaking in_prefill_requests.
        self.assertNotIn(self.engine_url, self.monitor.in_decoding_requests)

    def test_default_reached_decode_is_true_for_backward_compatibility(self):
        # Existing callers (e.g. the multipart/transcription proxy path) call
        # on_request_complete() without the new kwarg -- must keep behaving
        # exactly as before.
        self.monitor.on_new_request(self.engine_url, self.request_id, timestamp=0.0)
        self.monitor.on_request_response(
            self.engine_url, self.request_id, timestamp=0.1
        )

        self.monitor.on_request_complete(
            self.engine_url, self.request_id, timestamp=0.2
        )
        self.assertEqual(self.monitor.in_decoding_requests[self.engine_url], 0)

    def test_on_request_complete_pops_leaking_dicts(self):
        key = (self.engine_url, self.request_id)
        self.monitor.on_new_request(self.engine_url, self.request_id, timestamp=0.0)
        self.monitor.on_request_response(
            self.engine_url, self.request_id, timestamp=0.1
        )
        self.assertIn(key, self.monitor.request_start_time)
        self.assertIn(key, self.monitor.first_token_time)

        self.monitor.on_request_complete(
            self.engine_url, self.request_id, timestamp=0.2, reached_decode=True
        )
        self.assertNotIn(
            key,
            self.monitor.request_start_time,
            "request_start_time entry must be released on completion, or it "
            "leaks one entry per request for the life of the process "
            "(production-stack#707).",
        )
        self.assertNotIn(
            key,
            self.monitor.first_token_time,
            "first_token_time entry must be released on completion for the "
            "same reason.",
        )

    def test_on_request_complete_pops_request_start_time_even_without_first_token(self):
        # A request that never reaches decode still populated request_start_time
        # in on_new_request(); on_request_complete() must still release it.
        key = (self.engine_url, self.request_id)
        self.monitor.on_new_request(self.engine_url, self.request_id, timestamp=0.0)
        self.assertIn(key, self.monitor.request_start_time)

        self.monitor.on_request_complete(
            self.engine_url, self.request_id, timestamp=0.2, reached_decode=False
        )
        self.assertNotIn(key, self.monitor.request_start_time)


if __name__ == "__main__":
    unittest.main()
