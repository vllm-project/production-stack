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
import time
from collections import deque
from dataclasses import dataclass
from numbers import Number
from typing import Deque, Dict, Tuple, Set, List

from vllm_router.log import init_logger

logger = init_logger(__name__)


class SingletonMeta(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            instance = super().__call__(*args, **kwargs)
            cls._instances[cls] = instance
        return cls._instances[cls]


@dataclass
class RequestStats:
    # Number of queries per second
    qps: float
    # Average time-to-first-token (TTFT) in seconds
    ttft: float
    # Total number of requests during prefilling
    in_prefill_requests: int
    # Total number of requests during decoding
    in_decoding_requests: int
    # Total number of requests finished
    finished_requests: int
    # How long the engine has been serving requests (uptime)
    uptime: int
    # Average decoding length (time from first token to completion)
    avg_decoding_length: float
    # Average overall latency (from request arrival to completion)
    avg_latency: float
    # Average inter-token latency (if available; default -1 if not computed)
    avg_itl: float
    # Number of swapped requests (moved from GPU to CPU)
    num_swapped_requests: int
    # Engine prefill computation speed
    engine_prefill_comp_speed: float
    # Uncomputed prefix tokens
    uncomputed_prefix_tokens: int


class TimePeriods:
    """
    Utility for computing length of overlapping time periods.
    """
    def __init__(self):
        self.periods: List[Tuple[float, float]] = []

    def union(self, begin: float, end: float):
        overlap_periods = []
        for i, period in enumerate(self.periods):
            if ((begin >= period[0] and begin <= period[1]) or \
                    (end >= period[0] and end <= period[1])) or \
                ((period[0] >= begin and period[0] <= end) or \
                 (period[1] >= begin and period[1] <= end)):
                self.periods[i] = (min(period[0], begin), max(period[1], end))
                overlap_periods.append(i)
        if len(overlap_periods) == 0:
            self.periods.append((begin, end))
            return
        if len(overlap_periods) == 1:
            return
        # merge all overlapping periods
        merge_begin = min([self.periods[i][0] for i in overlap_periods])
        merge_end = max([self.periods[i][1] for i in overlap_periods])

        remove_indices = set(overlap_periods)
        new_periods = [period for i, period in enumerate(self.periods) if i not in remove_indices]
        self.periods = new_periods
        self.periods.append((merge_begin, merge_end))

    def compute_length(self) -> float:
        return sum([period[1] - period[0] for period in self.periods])


class MovingAverageMonitor:
    """
    Monitors the average of values in a sliding window.
    """

    def __init__(self, sliding_window_size: float):
        self.sliding_window_size = sliding_window_size
        self.timestamps: Deque[float] = deque()
        self.values: Deque[float] = deque()

    def update(self, timestamp: float, value: float):
        """
        Update the throughput monitor with a new timestamp

        Args:
            timestamp: The timestamp of the data point.
            value: The value of the data point.

        This method adds the new data point to the sliding window and
        removes any data point that is older than the sliding window size.
        """
        self.timestamps.append(timestamp)
        self.values.append(value)
        while (
            self.timestamps
            and self.timestamps[0] < timestamp - self.sliding_window_size
        ):
            self.timestamps.popleft()
            self.values.popleft()

    def update_no_value(self, timestamp: float):
        """
        Update the throughput monitor with a new timestamp with no value
        """
        while (
            len(self.timestamps) > 0
            and self.timestamps[0] < timestamp - self.sliding_window_size
        ):
            self.timestamps.popleft()
            self.values.popleft()

    def get_average(self) -> float:
        return sum(self.values) / len(self.values) if self.values else -1

    def get_sum(self) -> float:
        return sum(self.values)


class RequestStatsCacheInfo:
    """
    Cache information.
    """
    def __int__(self):
        self.num_prefix_tokens : int = 0
        self.num_cached_tokens : int = 0


class RequestStatsMonitor(metaclass=SingletonMeta):
    """
    Monitors the request statistics of all serving engines.
    """

    # NOTE (ApostaC): Currently, QPS is calculated based on the number of
    # arrived requests in the sliding window, but the inter_token_latency and
    # ttft are calculated based on the number of completed requests in the
    # sliding window.
    def __init__(self, sliding_window_size: float = None):
        if hasattr(self, "_initialized"):
            return
        if sliding_window_size is None:
            raise ValueError(
                "RequestStatsMonitor must be initialized with sliding_window_size"
            )
        self.sliding_window_size = sliding_window_size
        self.qps_monitors: Dict[str, MovingAverageMonitor] = {}
        self.ttft_monitors: Dict[str, MovingAverageMonitor] = {}

        # The time when the request is coming (engine_url, request_id) -> timestamp
        self.request_start_time: Dict[Tuple[str, str], float] = {}
        # Record time when first token is received: (engine_url, request_id) -> timestamp
        self.first_token_time: Dict[Tuple[str, str], float] = {}
        # The number of cached prefix tokens
        self.cache_infos: Dict[Tuple[str, str], RequestStatsCacheInfo] = {}

        # Number of requests in different stages (from the start of the router)
        self.in_prefill_requests: Dict[str, int] = {}
        self.in_decoding_requests: Dict[str, int] = {}
        self.finished_requests: Dict[str, int] = {}
        # New monitors for overall latency and decoding length
        self.latency_monitors: Dict[str, MovingAverageMonitor] = {}
        self.decoding_length_monitors: Dict[str, MovingAverageMonitor] = {}

        # Counter for swapped requests
        self.swapped_requests: Dict[str, int] = {}

        self.first_query_time: float = None
        self._initialized = True

    def on_new_request(self, engine_url: str,
                       request_id: str,
                       timestamp: float,
                       cache_info: RequestStatsCacheInfo = None):
        """
        Tell the monitor that a new request has been created.

        Args:
            engine_url: The URL of the serving engine
            request_id: The global request ID
            timestamp: the timestamp when the request was created
            cache_info: The cache information
        """
        self.request_start_time[(engine_url, request_id)] = timestamp

        if cache_info is not None:
            self.cache_infos[(engine_url, request_id)] = cache_info

        if engine_url not in self.in_prefill_requests:
            self.in_prefill_requests[engine_url] = 0
        self.in_prefill_requests[engine_url] += 1

        if engine_url not in self.qps_monitors:
            self.qps_monitors[engine_url] = MovingAverageMonitor(
                self.sliding_window_size
            )
        self.qps_monitors[engine_url].update(timestamp, 1)

        if engine_url not in self.latency_monitors:
            self.latency_monitors[engine_url] = MovingAverageMonitor(
                self.sliding_window_size
            )

        if self.first_query_time is None:
            self.first_query_time = timestamp

    def on_request_response(self, engine_url: str, request_id: str, timestamp: float):
        """
        Tell the monitor that a response token has been received for a request.

        Args:
            engine_url: The URL of the serving engine
            request_id: The global request ID
            timestamp: The timestamp when the response token was received
        """
        if (engine_url, request_id) not in self.request_start_time:
            return
        # Record first token time (do not pop so we can compute overall latency later)
        self.first_token_time[(engine_url, request_id)] = timestamp

        if engine_url not in self.in_decoding_requests:
            self.in_decoding_requests[engine_url] = 0
        self.in_prefill_requests[engine_url] = max(
            0, self.in_prefill_requests.get(engine_url, 1) - 1
        )
        self.in_decoding_requests[engine_url] += 1

        if engine_url not in self.ttft_monitors:
            self.ttft_monitors[engine_url] = MovingAverageMonitor(
                self.sliding_window_size
            )
        # Update TTFT as time from request start to first token
        # ttft = timestamp - self.request_start_time[(engine_url, request_id)]
        start_time = self.request_start_time[(engine_url, request_id)]
        ttft = timestamp - start_time
        self.ttft_monitors[engine_url].update(timestamp, ttft)

    def on_request_complete(self, engine_url: str, request_id: str, timestamp: float):
        """
        Tell the monitor that a request has been completed.

        Args:
            engine_url: The URL of the serving engine
            request_id: The global request ID
            timestamp: The timestamp when the request was completed
        """
        if engine_url not in self.finished_requests:
            self.finished_requests[engine_url] = 0
        self.in_decoding_requests[engine_url] = max(
            0, self.in_decoding_requests.get(engine_url, 1) - 1
        )
        self.finished_requests[engine_url] += 1

        if request_start_time := self.request_start_time.get((engine_url, request_id)):
            self.latency_monitors[engine_url].update(
                timestamp, time.time() - request_start_time
            )

    def on_request_swapped(self, engine_url: str, request_id: str, timestamp: float):
        # This function should be called if a request is determined to be swapped from GPU to CPU.
        """
        Tell the monitor that a request has been swapped from GPU to CPU.

        Args:
            engine_url: The URL of the serving engine
            request_id: The global request ID
            timestamp: The timestamp when the request was swapped
        """
        if engine_url not in self.swapped_requests:
            self.swapped_requests[engine_url] = 0
        self.swapped_requests[engine_url] += 1

    def get_request_stats(self, current_time: float, urls: List[str] = None) -> Dict[str, RequestStats]:
        """
        Get the request statistics for each serving engine

        Args:
            current_time: The current timestamp in seconds
            urls: The URLs of engines

        Returns:
            A dictionary where the key is the serving engine URL and the value
            is the request statistics for that engine.
            The TTFT and inter token latency will be -1 if there is no requests
            finished in the sliding window.
        """
        if urls is None:
            urls = set(self.in_prefill_requests.keys()).union(
                set(self.in_decoding_requests.keys())
            )
        ret = {}
        for engine_url in urls:
            if engine_url not in self.qps_monitors:
                qps = -1
            else:
                # Update the monitors
                self.qps_monitors[engine_url].update_no_value(current_time)
                qps = self.qps_monitors[engine_url].get_sum() / self.sliding_window_size

            if engine_url not in self.ttft_monitors:
                ttft = -1
            else:
                # Update the monitors
                self.ttft_monitors[engine_url].update_no_value(current_time)
                ttft = self.ttft_monitors[engine_url].get_average()

            in_prefill = self.in_prefill_requests.get(engine_url, 0)
            in_decoding = self.in_decoding_requests.get(engine_url, 0)
            finished = self.finished_requests.get(engine_url, 0)

            if engine_url in self.decoding_length_monitors:
                avg_dec_len = self.decoding_length_monitors[engine_url].get_average()
            else:
                avg_dec_len = -1

            if engine_url in self.latency_monitors:
                avg_lat = self.latency_monitors[engine_url].get_average()
            else:
                avg_lat = -1

            # For avg_itl, if not computed, default to -1.
            avg_itl_val = -1

            if engine_url in self.swapped_requests:
                swapped = self.swapped_requests[engine_url]
            else:
                swapped = 0


            engine_prefill_comp_speed = self._calc_engine_prefill_comp_speed(current_time, engine_url)
            uncomputed_prefix_tokens = self._get_uncomputed_prefix_tokens(engine_url)

            ret[engine_url] = RequestStats(
                qps=qps,
                ttft=ttft,
                in_prefill_requests=in_prefill,
                in_decoding_requests=in_decoding,
                finished_requests=finished,
                uptime=(
                    current_time - self.first_query_time if self.first_query_time else 0
                ),
                avg_decoding_length=avg_dec_len,
                avg_latency=avg_lat,
                avg_itl=avg_itl_val,
                num_swapped_requests=swapped,
                engine_prefill_comp_speed=engine_prefill_comp_speed,
                uncomputed_prefix_tokens=uncomputed_prefix_tokens,
            )
        return ret

    def _calc_engine_prefill_comp_speed(self, current_time: float, engine_url: str) -> float:
        min_start_time = current_time - self.sliding_window_size
        prefill_periods = TimePeriods()
        total_comp_amount = 0
        for (url, request_id), start_time in self.request_start_time.items():
            if url != engine_url or start_time < min_start_time:
                continue
            if ((url, request_id) not in self.first_token_time or
                    (url, request_id) not in self.cache_infos):
                continue

            cache_info = self.cache_infos[(url, request_id)]
            computed_tokens = cache_info.num_prefix_tokens - cache_info.num_cached_tokens
            if computed_tokens > 0:
                prefill_periods.union(start_time, self.first_token_time[(url, request_id)])
                # find computation amount by trapezoid area formula
                top = cache_info.num_cached_tokens
                bottom = cache_info.num_prefix_tokens - 1
                height = computed_tokens
                total_comp_amount += (top + bottom) * height / 2

        length = prefill_periods.compute_length()
        if length > 0:
            return total_comp_amount / length
        return -1

    def _get_uncomputed_prefix_tokens(self, engine_url: str) -> int:
        uncomputed_prefix_tokens = 0
        for (url, request_id), cache_info in self.cache_infos.items():
            if url != engine_url or (url, request_id) in self.first_token_time:
                continue
            uncomputed_prefix_tokens += (cache_info.num_prefix_tokens -
                                         cache_info.num_cached_tokens)
        return uncomputed_prefix_tokens


def initialize_request_stats_monitor(sliding_window_size: float):
    return RequestStatsMonitor(sliding_window_size)


def get_request_stats_monitor():
    return RequestStatsMonitor()
