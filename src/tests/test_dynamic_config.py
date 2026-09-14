import threading

import pytest
from fastapi import FastAPI

from vllm_router.dynamic_config import (
    DynamicConfigWatcher,
    DynamicRouterConfig,
    initialize_dynamic_config_watcher,
)
from vllm_router.utils import SingletonMeta


def _initialize_watcher(app):
    return initialize_dynamic_config_watcher(
        "unused.json",
        "JSON",
        60,
        DynamicRouterConfig(service_discovery="static", routing_logic="roundrobin"),
        app,
    )


def test_watcher_thread_is_daemon(monkeypatch):
    monkeypatch.delitem(SingletonMeta._instances, DynamicConfigWatcher, raising=False)
    monkeypatch.setattr(threading.Thread, "start", lambda _: None)

    watcher = _initialize_watcher(FastAPI())

    assert watcher.watcher_thread.daemon is True


def test_invalid_app_is_rejected_before_watcher_starts(monkeypatch):
    monkeypatch.delitem(SingletonMeta._instances, DynamicConfigWatcher, raising=False)

    def fail_if_started(_):
        pytest.fail("watcher started before app validation")

    monkeypatch.setattr(threading.Thread, "start", fail_if_started)

    with pytest.raises(AssertionError):
        _initialize_watcher(object())
