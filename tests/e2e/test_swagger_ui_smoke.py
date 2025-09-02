"""End-to-end Swagger UI smoke test.

Starts a mock backend + initializes router (subprocess) and validates core endpoints.
Skip unless RUN_E2E_SWAGGER=1 is set to avoid slowing default test runs.
"""

# Copyright 2024-2025 The vLLM Production Stack Authors.
# Licensed under the Apache License, Version 2.0.

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
MOCK_PATH = REPO_ROOT / "examples" / "mock_backend" / "main.py"


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_E2E_SWAGGER") != "1", reason="Set RUN_E2E_SWAGGER=1 to run E2E Swagger smoke test"
)


def wait_http(url: str, timeout: float = 10.0):
    end = time.time() + timeout
    while time.time() < end:
        try:
            r = requests.get(url, timeout=1)
            if r.status_code < 500:
                return True
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError(f"Timeout waiting for {url}")


@pytest.fixture(scope="module")
def processes():
    env = os.environ.copy()
    python = sys.executable
    backend_port = 18080
    router_port = 18081
    backend = subprocess.Popen(
        [python, str(MOCK_PATH), "--port", str(backend_port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    wait_http(f"http://localhost:{backend_port}/health")

    router = subprocess.Popen(
        [
            python,
            "-m",
            "vllm_router.app",
            "--service-discovery",
            "static",
            "--static-backends",
            f"http://localhost:{backend_port}",
            "--static-models",
            "gpt-3.5-turbo",
            "--static-aliases",
            "text-embedding-ada-002=gpt-3.5-turbo",
            "--routing-logic",
            "roundrobin",
            "--port",
            str(router_port),
            "--host",
            "0.0.0.0",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    wait_http(f"http://localhost:{router_port}/docs")
    yield {"backend": backend, "router": router, "router_port": router_port}
    for p in (router, backend):
        if p.poll() is None:
            p.send_signal(signal.SIGINT)
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()


def test_swagger_smoke(processes):
    base = f"http://localhost:{processes['router_port']}"
    # Basic endpoint checks
    r_docs = requests.get(f"{base}/docs")
    assert r_docs.status_code == 200

    chat_payload = {"model": "gpt-3.5-turbo", "messages": [{"role": "user", "content": "hi"}]}
    r_chat = requests.post(f"{base}/v1/chat/completions", json=chat_payload)
    assert r_chat.status_code == 200, r_chat.text

    bad = requests.post(f"{base}/v1/chat/completions", json={"messages": []})
    assert bad.status_code == 422

    comp_payload = {"model": "gpt-3.5-turbo", "prompt": "Hello"}
    r_comp = requests.post(f"{base}/v1/completions", json=comp_payload)
    assert r_comp.status_code == 200, r_comp.text

    emb_payload = {"model": "text-embedding-ada-002", "input": "Hello"}
    r_emb = requests.post(f"{base}/v1/embeddings", json=emb_payload)
    assert r_emb.status_code == 200, r_emb.text
