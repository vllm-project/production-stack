"""Sleep-mode detection from the vllm container spec.

The operator (VLLMRuntime) and the helm chart with modelSpec.command/args run
`vllm serve` as the container command and pass the model flags, extraArgs
included, as container args. `--enable-sleep-mode` then lives in `args`, and
the router must still see it, otherwise an engine that is asleep when it is
discovered is registered as awake and gets traffic.

The real __init__ loads a kubeconfig and starts a watcher thread, so the
instances are built with __new__ and given only the attributes they touch.
"""

import threading
from unittest.mock import MagicMock

import pytest
from kubernetes.client import V1Container, V1ObjectMeta, V1Pod, V1PodSpec

from vllm_router.service_discovery import (
    K8sPodIPServiceDiscovery,
    K8sServiceNameServiceDiscovery,
)

OPERATOR_COMMAND = ["/opt/venv/bin/vllm", "serve"]

CASES = [
    # no command override: flags can't be inspected, probe /is_sleeping
    (None, None, True),
    (None, ["--model", "m"], True),
    # flag in the command (helm default template)
    (["vllm", "serve", "m", "--enable-sleep-mode"], None, True),
    (["vllm", "serve", "m"], None, False),
    # flag in args (operator extraArgs, helm modelSpec.command + args)
    (OPERATOR_COMMAND, ["m", "--port", "8000", "--enable-sleep-mode"], True),
    (OPERATOR_COMMAND, ["m", "--port", "8000"], False),
    (OPERATOR_COMMAND, ["m", "--no-enable-sleep-mode"], False),
    # explicit value form, as some helm/k8s configs pass it
    (OPERATOR_COMMAND, ["m", "--enable-sleep-mode=true"], True),
    (OPERATOR_COMMAND, ["m", "--enable-sleep-mode=1"], True),
    (OPERATOR_COMMAND, ["m", "--enable-sleep-mode=false"], False),
    (["sh", "-c"], ["vllm serve m --enable-sleep-mode=True --port 8000"], True),
    # whole shell line in one entry
    (["sh", "-c"], ["vllm serve m --enable-sleep-mode --port 8000"], True),
    (["sh", "-c", "vllm serve m --enable-sleep-mode"], None, True),
    (["sh", "-c"], ["vllm serve m --port 8000"], False),
]


def _pod(command, args):
    return V1Pod(
        metadata=V1ObjectMeta(name="engine-0", labels={"model": "m"}),
        spec=V1PodSpec(
            containers=[
                V1Container(name="sidecar", command=["--enable-sleep-mode"]),
                V1Container(name="vllm", command=command, args=args),
            ]
        ),
    )


def _pod_ip_discovery(pod) -> K8sPodIPServiceDiscovery:
    d = K8sPodIPServiceDiscovery.__new__(K8sPodIPServiceDiscovery)
    d.namespace = "test-ns"
    d.k8s_api = MagicMock()
    d.k8s_api.read_namespaced_pod.return_value = pod
    return d


def _service_name_discovery(pod) -> K8sServiceNameServiceDiscovery:
    d = K8sServiceNameServiceDiscovery.__new__(K8sServiceNameServiceDiscovery)
    d.namespace = "test-ns"
    service = MagicMock()
    service.spec.selector = {"app": "vllm"}
    pods = MagicMock()
    pods.items = [pod]
    d.k8s_api = MagicMock()
    d.k8s_api.read_namespaced_service.return_value = service
    d.k8s_api.list_namespaced_pod.return_value = pods
    return d


@pytest.mark.parametrize("command,args,expected", CASES)
def test_pod_ip_sleep_mode_detection(command, args, expected):
    d = _pod_ip_discovery(_pod(command, args))
    assert d._check_engine_sleep_mode("engine-0") is expected


@pytest.mark.parametrize("command,args,expected", CASES)
def test_service_name_sleep_mode_detection(command, args, expected):
    d = _service_name_discovery(_pod(command, args))
    assert d._check_engine_sleep_mode("engine-svc") is expected


def test_operator_engine_discovered_asleep_is_registered_sleeping():
    d = _pod_ip_discovery(
        _pod(OPERATOR_COMMAND, ["m", "--port", "8000", "--enable-sleep-mode"])
    )
    d.available_engines = {}
    d.available_engines_lock = threading.Lock()
    d.known_models = set()
    d.known_models_lock = threading.Lock()
    d.port = "8000"
    d.event_loop_ready = threading.Event()
    d.event_loop = None
    d._get_model_info = MagicMock(return_value={})
    d._get_engine_sleep_status = MagicMock(return_value=True)

    d._add_engine("engine-0", "10.0.0.1", ["m"], "m")

    d._get_engine_sleep_status.assert_called_once_with("10.0.0.1")
    assert d.available_engines["engine-0"].sleep is True
