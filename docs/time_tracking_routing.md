
# TimeTrackingRouter

`TimeTrackingRouter` is a customizable routing strategy that selects the best endpoint for a request based on historical performance data. It balances **mean completion time**, **load**, and **latency variability** (standard deviation), helping optimize for quality of experience (QoE) in systems serving LLM or similar model endpoints.

---

## Features

- Tracks per-endpoint **mean** and **standard deviation** of completion times.
- Considers **current load** to avoid overloading busy endpoints.
- Assigns a **scoring function** to choose the optimal endpoint.
- Automatically updates endpoint stats based on request outcomes.

---

## Parameters

You can customize the importance of each routing factor using:

- `alpha`: Weight for **mean completion time**.
- `beta`: Weight for **current load**.
- `gamma`: Weight for **completion time standard deviation**.

### Default Configuration

```python
TimeTrackingRouter(alpha=1.0, beta=1.0, gamma=0.5)
```

---

## Classes

### `TimeTrackingRouter(RoutingInterface)`

Implements the routing logic:

- `route_request(...)`: Chooses the endpoint with the lowest score.
- `register_endpoint(endpoint)`: Initializes tracking for new endpoints.
- `update_stats(endpoint)`: Updates endpoint with latest performance stats.
- `record_completion(endpoint, duration)`: Records completion time after a request finishes.

### `EndpointStats`

Maintains historical performance for a single endpoint:

- `add_completion_time(time)`: Adds a new completion time.
- `mean()`: Returns mean of recorded times.
- `stdev()`: Returns standard deviation (returns `0.0` if insufficient data).

### `EndpointInfo`

Metadata for each endpoint:

```python
@dataclass
class EndpointInfo:
    url: str
    model_name: str
    added_timestamp: float
    model_label: str
    mean_completion_time: Optional[float]
    std_completion_time: Optional[float]
    current_load: Optional[int]
```

---

## Routing Algorithm

The score for each endpoint is computed as:

```
score = (alpha * mean_completion_time) + (beta * current_load) + (gamma * std_completion_time)
```

The endpoint with the **lowest score** is selected.

If an endpoint lacks data, it defaults to a score of zero for missing metrics (favoring exploration).

---

## Example Usage

```python
router = TimeTrackingRouter(alpha=1.0, beta=2.0, gamma=0.3)
chosen_url = await router.route_request(endpoints, engine_stats, request_stats, request, request_json)
router.record_completion(endpoint, duration=1.25)
```

---

## Notes

- Uses a fixed-size rolling window (`maxlen=100`) for tracking completion time history.
- Designed to plug into systems implementing `RoutingInterface`.

---

## Future Enhancements

- Add support for exponential decay or recency bias in stats.
- Consider request priority or user-level QoE history.
- Track token-level latency (e.g. TTFT, ITL).
