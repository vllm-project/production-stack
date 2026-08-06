import pytest

from vllm_router.service_discovery import _parse_static_known_models


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, set()),
        ("", set()),
        ("   ", set()),
        ("modelA", {"modelA"}),
        ("modelA,modelB", {"modelA", "modelB"}),
        ("  modelA , modelB ", {"modelA", "modelB"}),
        ("modelA,,modelB,", {"modelA", "modelB"}),
        ("modelA,modelA", {"modelA"}),
    ],
)
def test_parse_static_known_models(raw, expected):
    assert _parse_static_known_models(raw) == expected


def test_static_known_models_seed_marks_model_as_seen():
    """A pod-ip discovery seeded with static models reports them as seen even
    when no engine has ever been observed (issue #1003, scale-to-zero). The k8s
    client / watcher thread in __init__ is bypassed via __new__ so no cluster is
    required."""
    import threading

    from vllm_router import service_discovery as sd

    instance = sd.K8sPodIPServiceDiscovery.__new__(sd.K8sPodIPServiceDiscovery)
    instance.known_models = sd._parse_static_known_models("modelA,modelB")
    instance.known_models_lock = threading.Lock()

    assert instance.has_ever_seen_model("modelA") is True
    assert instance.has_ever_seen_model("modelC") is False
