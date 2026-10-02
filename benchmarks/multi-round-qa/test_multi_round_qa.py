import asyncio
import importlib
import json
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import FrameType
from typing import Callable, TypeAlias

import pandas as pd
import pytest

benchmark = importlib.import_module("multi-round-qa")
Trace: TypeAlias = Callable[[FrameType, str, object], "Trace | None"]


@pytest.fixture
def session() -> benchmark.UserSession:
    return benchmark.UserSession(
        user_config=benchmark.UserConfig(
            user_id=7,
            system_prompt_len=1,
            user_info_len=1,
            answer_len=2,
            gap_between_requests=1,
            num_rounds=2,
            enable_user_id=True,
        )
    )


def test_empty_summary(session: benchmark.UserSession) -> None:
    summary = session.summary()

    assert summary.empty
    assert list(summary.columns) == [
        "prompt_tokens",
        "generation_tokens",
        "ttft",
        "generation_time",
        "user_id",
        "question_id",
        "launch_time",
        "finish_time",
    ]


def test_summary_during_streamed_response(session: benchmark.UserSession) -> None:
    summary_started = threading.Event()
    second_request = threading.Event()
    release_response = threading.Event()
    update_finished = threading.Event()
    histories: list[list[dict[str, str]]] = []

    class Backend(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            assert self.path == "/v1/chat/completions"
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert body["stream"] is True
            assert body["stream_options"]["include_usage"] is True
            histories.append(body["messages"])
            round_number: int = len(histories)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            chunk: dict[str, object] = {
                "id": f"chatcmpl-{round_number}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "content": "first" if round_number == 1 else "second"
                        },
                        "finish_reason": None,
                    }
                ],
            }
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()
            if round_number == 2:
                second_request.set()
                assert release_response.wait(timeout=5)
            chunk["choices"] = []
            chunk["usage"] = {
                "prompt_tokens": 11 * round_number,
                "completion_tokens": round_number,
                "total_tokens": 12 * round_number,
            }
            self.wfile.write(f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode())
            self.wfile.flush()

    def trace(frame: FrameType, event: str, argument: object) -> Trace | None:
        if frame.f_code is benchmark.UserSession._update_result.__code__:
            if event == "return" and len(session.finish_times) == 2:
                update_finished.set()
            return trace
        if frame.f_code is not benchmark.UserSession.summary.__code__:
            return None
        if event == "line":
            data = frame.f_locals.get("df")
            if (
                second_request.is_set()
                and data is not None
                and "generation_tokens" in data
                and "ttft" not in data
                and not summary_started.is_set()
            ):
                summary_started.set()
                release_response.set()
                update_finished.wait(timeout=0.5)
        return trace

    server = ThreadingHTTPServer(
        server_address=("127.0.0.1", 0), RequestHandlerClass=Backend
    )
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    previous_trace = sys.gettrace()
    previous_thread_trace = threading.gettrace()
    sys.settrace(trace)
    threading.settrace(trace)
    executor = benchmark.RequestExecutor(
        base_url=f"http://127.0.0.1:{server.server_port}/v1",
        api_key="EMPTY",
        model="test-model",
    )
    try:
        session.step(timestamp=time.time(), request_executor=executor)
        benchmark.AsyncLoopWrapper.WaitLoop()
        first_summary = session.summary()
        assert len(first_summary) == 1

        session.step(timestamp=time.time() + 2, request_executor=executor)
        assert second_request.wait(timeout=5)
        summary = session.summary()
        assert summary_started.is_set()
        benchmark.AsyncLoopWrapper.WaitLoop()
        assert update_finished.is_set()
    finally:
        sys.settrace(previous_trace)
        threading.settrace(previous_thread_trace)
        release_response.set()
        benchmark.AsyncLoopWrapper.WaitLoop()
        asyncio.run_coroutine_threadsafe(
            coro=executor.client.close(), loop=executor.loop
        ).result(timeout=5)
        benchmark.AsyncLoopWrapper.StopLoop()
        executor.loop.close()
        benchmark.AsyncLoopWrapper._loop = None
        benchmark.AsyncLoopWrapper._thread = None
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)

    pd.testing.assert_frame_equal(left=summary, right=first_summary)
    final_summary = session.summary()
    pd.testing.assert_frame_equal(left=final_summary.iloc[:1], right=first_summary)
    assert final_summary["prompt_tokens"].tolist() == [11, 22]
    assert final_summary["generation_tokens"].tolist() == [1, 2]
    assert final_summary["user_id"].tolist() == [7, 7]
    assert final_summary["question_id"].tolist() == [1, 2]
    assert (final_summary["ttft"] >= 0).all()
    assert (final_summary["generation_time"] >= 0).all()
    assert (final_summary["finish_time"] >= final_summary["launch_time"]).all()
    assert histories[1][-2] == {"role": "assistant", "content": "first"}
    assert session.chat_history.history[-1] == {
        "role": "assistant",
        "content": "second",
    }
