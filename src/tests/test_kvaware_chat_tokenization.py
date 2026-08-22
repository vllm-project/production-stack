"""Unit tests for chat-completion tokenization in the KV-aware routers.

`kvaware` and `loadaware` place a request by asking the LMCache controller
which engine already holds KV for the request's token-id prefix. vLLM
engines cache KV for the token ids *after* chat-template application, so a
chat-completions body (a "messages" array, no "prompt" key) must be
tokenized through `apply_chat_template` - the old
`encode(request_json.get("prompt", ""))` tokenized the empty string, the
lookup matched nothing, and every chat request silently degraded to the
session/QPS fallback.

As in `test_loadaware_router.py`, the routers are built with `__new__` and
only the attributes the tokenize path reads, so no LMCache controller (and
no network) is needed.
"""

from typing import Any, Dict

import pytest
from uhashring import HashRing

import vllm_router.routers.routing_logic as routing_logic
from vllm_router.routers.routing_logic import (
    KvawareRouter,
    LoadAwareRouter,
    _extract_token_ids,
    _normalize_chat_messages,
    _tokenize_request_payload,
)


@pytest.fixture(autouse=True)
def lookup_msg_stub(monkeypatch):
    """`LookupMsg`/`QueryInstMsg` come from the optional lmcache dependency;
    stub them when absent so the routing tests run without the lmcache
    extra."""

    class _Msg:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    for name in ("LookupMsg", "QueryInstMsg"):
        if not hasattr(routing_logic, name):
            monkeypatch.setattr(routing_logic, name, _Msg, raising=False)


URL_A = "http://10.0.0.1:8000"
URL_B = "http://10.0.0.2:8000"
INST_A = "instance-a"
LOCAL = "LocalCPUBackend"
MODEL = "test-model"
CHAT_IDS = [101, 102, 103, 104, 105]
MESSAGES = [
    {"role": "system", "content": "You are terse."},
    {"role": "user", "content": "Hello there"},
]


class EndpointInfo:
    def __init__(self, url: str):
        self.url = url
        self.model_names = [MODEL]


class LookupRet:
    def __init__(self, layout_info: Dict[str, Any]):
        self.layout_info = layout_info


def endpoints(*urls):
    return [EndpointInfo(url=url) for url in urls]


class ChatTokenizer:
    """Records calls; template ids are disjoint from encode ids so a test
    can tell which path produced them."""

    def __init__(self):
        self.chat_template_calls = []
        self.encode_calls = []

    def apply_chat_template(
        self, messages, add_generation_prompt=False, tokenize=False
    ):
        self.chat_template_calls.append(
            {
                "messages": messages,
                "add_generation_prompt": add_generation_prompt,
                "tokenize": tokenize,
            }
        )
        return list(CHAT_IDS)

    def encode(self, prompt):
        self.encode_calls.append(prompt)
        return [1] * len(prompt)


class TemplatelessTokenizer(ChatTokenizer):
    """A tokenizer with no chat template, as `apply_chat_template` raises on
    base models."""

    def apply_chat_template(self, *args, **kwargs):
        raise ValueError("no chat template defined")


# --- local tokenization -------------------------------------------------------


def test_messages_tokenize_through_the_chat_template():
    tokenizer = ChatTokenizer()
    ids = _extract_token_ids(tokenizer, {"messages": MESSAGES})
    assert ids == CHAT_IDS
    call = tokenizer.chat_template_calls[0]
    assert call["add_generation_prompt"] is True
    assert call["tokenize"] is True
    assert tokenizer.encode_calls == []


def test_prompt_requests_keep_the_plain_encode_path():
    tokenizer = ChatTokenizer()
    ids = _extract_token_ids(tokenizer, {"prompt": "hello"})
    assert ids == [1] * len("hello")
    assert tokenizer.chat_template_calls == []


def test_multimodal_content_parts_are_flattened_to_their_text():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "describe"},
                {"type": "image_url", "image_url": {"url": "data:image/png;..."}},
                {"type": "text", "text": "this image"},
            ],
        }
    ]
    normalized = _normalize_chat_messages(messages)
    assert normalized == [{"role": "user", "content": "describe this image"}]
    # The request body itself is never mutated.
    assert isinstance(messages[0]["content"], list)


def test_null_text_part_becomes_an_empty_string():
    # {"type": "text", "text": null} is valid JSON a client can send; .get
    # with a default only covers a MISSING key, so an explicit null must not
    # reach " ".join as None.
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": None},
                {"type": "text", "text": "hello"},
            ],
        }
    ]
    normalized = _normalize_chat_messages(messages)
    assert normalized == [{"role": "user", "content": " hello"}]


def test_none_content_becomes_an_empty_string():
    messages = [{"role": "assistant", "content": None, "tool_calls": [{"id": "1"}]}]
    normalized = _normalize_chat_messages(messages)
    assert normalized[0]["content"] == ""
    assert normalized[0]["tool_calls"] == [{"id": "1"}]


def test_string_content_messages_pass_through_untouched():
    assert _normalize_chat_messages(MESSAGES) == MESSAGES


# --- the remote /tokenize fallback payload ------------------------------------


def test_chat_bodies_use_the_tokenize_chat_request_form():
    payload = _tokenize_request_payload(MODEL, {"messages": MESSAGES})
    assert payload == {
        "model": MODEL,
        "messages": MESSAGES,
        "add_generation_prompt": True,
    }


def test_prompt_bodies_keep_the_completion_form():
    assert _tokenize_request_payload(MODEL, {"prompt": "hello"}) == {
        "model": MODEL,
        "prompt": "hello",
    }


# --- through the routers ------------------------------------------------------


@pytest.mark.asyncio
async def test_kvaware_routes_chat_requests_via_the_kv_lookup_path():
    """The regression this file exists for: a messages-form body must reach
    the controller as non-empty, template-aligned token ids and route to the
    KV holder - not tokenize as "" and fall back to session/QPS."""
    router = KvawareRouter.__new__(KvawareRouter)
    router.tokenizer = ChatTokenizer()
    router.threshold = 2000
    router.instance_id_to_ip = {INST_A: URL_A}
    router.session_key = None
    router.hash_ring = HashRing()
    seen = {}

    async def query_manager(msg):
        seen["tokens"] = msg.tokens
        return LookupRet({INST_A: (LOCAL, len(CHAT_IDS))})

    router.query_manager = query_manager
    url = await router.route_request(
        endpoints(URL_A, URL_B), {}, {}, None, {"messages": MESSAGES}
    )
    assert seen["tokens"] == CHAT_IDS
    assert url == URL_A


@pytest.mark.asyncio
async def test_loadaware_tokenizes_chat_requests_through_the_template():
    router = LoadAwareRouter.__new__(LoadAwareRouter)
    router.tokenizer = ChatTokenizer()
    ids = await router.tokenize_prompt(endpoints(URL_A), {"messages": MESSAGES})
    assert ids == CHAT_IDS


@pytest.mark.asyncio
async def test_prompt_requests_are_unchanged_by_the_chat_support():
    router = LoadAwareRouter.__new__(LoadAwareRouter)
    tokenizer = ChatTokenizer()
    router.tokenizer = tokenizer
    ids = await router.tokenize_prompt(endpoints(URL_A), {"prompt": "hello"})
    assert ids == [1] * len("hello")
    assert tokenizer.chat_template_calls == []


@pytest.mark.asyncio
async def test_remote_tokenize_fallback_sends_the_messages_for_chat(monkeypatch):
    """A tokenizer without a chat template falls back to the engine's
    /tokenize with the original messages (vLLM's TokenizeChatRequest), not
    {"prompt": ""}."""
    router = LoadAwareRouter.__new__(LoadAwareRouter)
    router.tokenizer = TemplatelessTokenizer()
    captured = {}

    class Response:
        @staticmethod
        def json():
            return {"count": len(CHAT_IDS), "tokens": CHAT_IDS}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return Response()

    monkeypatch.setattr(routing_logic.requests, "post", fake_post)
    ids = await router.tokenize_prompt(endpoints(URL_A), {"messages": MESSAGES})
    assert ids == CHAT_IDS
    assert captured["url"] == URL_A + "/tokenize"
    assert captured["json"]["messages"] == MESSAGES
    assert captured["json"]["add_generation_prompt"] is True
    assert "prompt" not in captured["json"]
