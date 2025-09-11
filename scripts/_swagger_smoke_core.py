"""Reusable Swagger smoke test core logic for CLI + pytest.

Keep this dependency-light. Do not import internal router modules here.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Dict, List

import requests


@dataclass
class TestResult:
    name: str
    success: bool
    detail: str = ""
    extra: Dict = field(default_factory=dict)


class SwaggerUITester:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.results: List[TestResult] = []

    def record(self, name: str, success: bool, detail: str = "", **extra):
        self.results.append(TestResult(name, success, detail, extra))

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def test_docs(self):
        try:
            r = self.session.get(self._url("/docs"), timeout=5)
            self.record("/docs", r.status_code == 200, f"status={r.status_code}")
        except Exception as e:  # pragma: no cover
            self.record("/docs", False, str(e))

    def test_openapi(self):
        try:
            r = self.session.get(self._url("/openapi.json"), timeout=5)
            if r.status_code != 200:
                self.record("openapi", False, f"status={r.status_code}")
                return
            schema = r.json()
            paths = schema.get("paths", {})
            expected = ["/v1/chat/completions", "/v1/completions", "/v1/embeddings"]
            missing = [p for p in expected if p not in paths]
            self.record(
                "openapi", not missing, "ok" if not missing else f"missing={missing}"
            )
        except Exception as e:  # pragma: no cover
            self.record("openapi", False, str(e))

    def test_core_endpoints(self):
        # chat valid
        chat = {
            "model": "gpt-3.5-turbo",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 4,
        }
        r = self.session.post(self._url("/v1/chat/completions"), json=chat, timeout=8)
        self.record("chat_valid", r.status_code == 200, f"status={r.status_code}")
        # chat 422
        r2 = self.session.post(
            self._url("/v1/chat/completions"), json={"messages": []}, timeout=5
        )
        self.record("chat_422", r2.status_code == 422, f"status={r2.status_code}")
        # completions
        comp = {"model": "gpt-3.5-turbo", "prompt": "Hello", "max_tokens": 5}
        r3 = self.session.post(self._url("/v1/completions"), json=comp, timeout=8)
        self.record(
            "completions_valid", r3.status_code == 200, f"status={r3.status_code}"
        )
        # embeddings
        emb = {"model": "text-embedding-ada-002", "input": "hello"}
        r4 = self.session.post(self._url("/v1/embeddings"), json=emb, timeout=8)
        self.record(
            "embeddings_valid", r4.status_code == 200, f"status={r4.status_code}"
        )

    def run(self):
        start = time.time()
        self.test_docs()
        self.test_openapi()
        self.test_core_endpoints()
        elapsed = time.time() - start
        passed = sum(1 for r in self.results if r.success)
        return passed == len(self.results), elapsed, self.results


def run_smoke(base_url: str) -> bool:
    tester = SwaggerUITester(base_url)
    ok, elapsed, results = tester.run()
    print(
        f"Swagger smoke: {passed_count(results)}/{len(results)} passed in {elapsed:.2f}s"
    )
    for r in results:
        icon = "✅" if r.success else "❌"
        print(f" {icon} {r.name} - {r.detail}")
    return ok


def passed_count(results: List[TestResult]) -> int:
    return sum(1 for r in results if r.success)
