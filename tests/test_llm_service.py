"""Task routing, fallback policy and the OpenAI-compatible client."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from pydantic import BaseModel

import config
import services.llm_service as llm
from core.exceptions import LLMOverloadedError, LLMUnavailableError


class Payload(BaseModel):
    ok: bool = False


class _BusyProvider(llm.LLMProvider):
    """Provider that is always at capacity, counting calls."""

    name = "busy"
    model = "test"

    def __init__(self) -> None:
        self.calls = 0

    @property
    def available(self) -> bool:
        return True

    def generate(self, prompt, *, system=None, json_mode=True,
                 temperature=None, response_schema=None):
        self.calls += 1
        raise LLMOverloadedError("busy")


class _OkProvider(llm.LLMProvider):
    name = "ok"
    model = "test"

    def __init__(self, text: str = "ok") -> None:
        self.text = text
        self.calls = 0

    @property
    def available(self) -> bool:
        return True

    def generate(self, prompt, *, system=None, json_mode=True,
                 temperature=None, response_schema=None):
        self.calls += 1
        return llm.LLMResponse(text=self.text, model=self.model)


class _BadJsonProvider(_OkProvider):
    name = "bad-json"

    def __init__(self) -> None:
        super().__init__("this is not JSON")


class _SmallPromptProvider(_OkProvider):
    name = "small-prompt"
    max_prompt_chars = 5


def test_capacity_errors_are_classified_separately():
    assert isinstance(
        llm.classify_provider_error(Exception("503 UNAVAILABLE. high demand")),
        LLMOverloadedError,
    )
    assert isinstance(
        llm.classify_provider_error(Exception("429 RESOURCE_EXHAUSTED")),
        LLMOverloadedError,
    )
    hard = llm.classify_provider_error(Exception("401 invalid api key"))
    assert isinstance(hard, LLMUnavailableError)
    assert not isinstance(hard, LLMOverloadedError)


def test_generate_json_does_not_multiply_capacity_retries():
    provider = _BusyProvider()
    service = llm.LLMService(provider)
    with pytest.raises(LLMOverloadedError):
        service.generate_json("prompt", Payload)
    assert provider.calls == 1


def test_default_provider_uses_the_configured_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "nvidia/nemotron-3.5-super-vl:free")
    config.get_settings.cache_clear()
    provider = llm._default_provider()
    assert isinstance(provider, llm.OpenAICompatibleProvider)
    assert provider.base_url == "https://openrouter.ai/api/v1"
    assert provider.model == "nvidia/nemotron-3.5-super-vl:free"


def test_default_provider_uses_preset_model(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "17")
    config.get_settings.cache_clear()
    provider = llm._default_provider()
    assert isinstance(provider, llm.OpenAICompatibleProvider)
    assert provider.base_url == "https://api.groq.com/openai/v1"
    assert provider.model == "openai/gpt-oss-20b"
    assert provider.timeout == 17


def test_groq_api_key_is_accepted_without_llm_api_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    config.get_settings.cache_clear()
    provider = llm._default_provider()
    assert isinstance(provider, llm.OpenAICompatibleProvider)
    assert provider.base_url == "https://api.groq.com/openai/v1"
    assert provider.available


def test_no_provider_when_llm_is_disabled(monkeypatch):
    monkeypatch.setenv("LLM_ENABLED", "0")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    config.get_settings.cache_clear()
    assert not llm._default_provider().available


def test_default_routes_put_gemini_on_extraction_and_groq_on_writing(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    config.get_settings.cache_clear()

    service = llm.LLMService()

    extraction = service.routes["extraction"]
    assert [(p.name, p.model) for p in extraction[:2]] == [
        ("gemini", "gemini-3.8-flash"),
        ("gemini", "gemini-3.5-flash-lite"),
    ]
    assert extraction[-1].name == "groq"
    assert service.routes["writing"][0].name == "groq"
    assert service.routes["writing"][0].model == "openai/gpt-oss-120b"
    assert service.routes["reasoning"][0].name == "gemini"


def test_route_falls_back_to_the_next_provider_on_capacity_error():
    busy = _BusyProvider()
    ok = _OkProvider()
    service = llm.LLMService(routes={"writing": [busy, ok]}, cooldown_seconds=60)

    assert service.generate_text("write", task="writing") == "ok"
    assert busy.calls == 1
    assert ok.calls == 1


def test_rate_limited_provider_is_skipped_by_the_next_request():
    busy = _BusyProvider()
    ok = _OkProvider()
    service = llm.LLMService(routes={"writing": [busy, ok]}, cooldown_seconds=60)

    service.generate_text("first", task="writing")
    service.generate_text("second", task="writing")

    assert busy.calls == 1
    assert ok.calls == 2


def test_all_providers_cooling_down_raises_a_clear_overload_error():
    busy = _BusyProvider()
    service = llm.LLMService(routes={"writing": [busy]}, cooldown_seconds=60)

    with pytest.raises(LLMOverloadedError):
        service.generate_text("first", task="writing")
    with pytest.raises(LLMOverloadedError) as excinfo:
        service.generate_text("second", task="writing")

    assert "cooling down" in str(excinfo.value)
    assert busy.calls == 1


def test_provider_with_a_small_prompt_budget_is_skipped_for_long_inputs():
    small = _SmallPromptProvider()
    ok = _OkProvider()
    service = llm.LLMService(routes={"writing": [small, ok]}, cooldown_seconds=60)

    assert service.generate_text("a prompt that is too long", task="writing") == "ok"
    assert small.calls == 0
    assert ok.calls == 1


def test_bad_json_falls_back_to_the_next_provider():
    bad = _BadJsonProvider()
    good = _OkProvider('{"ok": true}')
    service = llm.LLMService(routes={"extraction": [bad, good]}, cooldown_seconds=60)

    result = service.generate_json("extract", Payload, attempts=1, task="extraction")

    assert result.ok is True
    assert bad.calls == 1
    assert good.calls == 1


def test_gemini_uses_its_openai_compatible_endpoint(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    config.get_settings.cache_clear()

    provider = llm._default_provider()

    assert isinstance(provider, llm.OpenAICompatibleProvider)
    assert provider.base_url == "https://generativelanguage.googleapis.com/v1beta/openai"
    assert provider.model == "gemini-3.8-flash"


@respx.mock
def test_gemini_route_uses_the_openai_compatible_chat_endpoint(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    config.get_settings.cache_clear()
    route = respx.post(
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    ).mock(return_value=httpx.Response(200, json={
        "choices": [{"message": {"content": "extracted"}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 3},
    }))

    service = llm.LLMService()
    assert service.generate_text("extract this", task="extraction") == "extracted"

    body = json.loads(route.calls.last.request.content)
    assert body["model"] == "gemini-3.8-flash"
    assert route.calls.last.request.headers["Authorization"] == "Bearer gemini-key"


@respx.mock
def test_openai_compatible_request_shape_and_parsing():
    route = respx.post("https://example.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": '{"ok": true}'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        })
    )
    provider = llm.OpenAICompatibleProvider("key", "https://example.test/v1",
                                            "test-model", timeout=5, name="custom")
    result = provider.generate("parse this", json_mode=True, response_schema=Payload)

    assert result.text == '{"ok": true}'
    assert result.prompt_tokens == 10 and result.output_tokens == 5
    body = json.loads(route.calls.last.request.content)
    assert body["model"] == "test-model"
    assert body["response_format"] == {"type": "json_object"}
    assert body["max_tokens"] == config.get_settings().llm_max_output_tokens
    assert route.calls.last.request.headers["Authorization"] == "Bearer key"


@respx.mock
def test_openai_compatible_retries_capacity_errors_then_raises(monkeypatch):
    monkeypatch.setattr(llm, "_RETRY_INITIAL_WAIT", 0.0)
    route = respx.post("https://example.test/v1/chat/completions").mock(
        return_value=httpx.Response(503, text="high demand")
    )
    provider = llm.OpenAICompatibleProvider("key", "https://example.test/v1",
                                            "test-model", timeout=5, name="custom")
    with pytest.raises(LLMOverloadedError):
        provider.generate("parse this")
    assert route.call_count == llm._RETRY_ATTEMPTS


@respx.mock
def test_openai_compatible_retries_without_json_mode_when_rejected():
    route = respx.post("https://example.test/v1/chat/completions").mock(
        side_effect=[
            httpx.Response(400, text='{"error":"response_format is not supported"}'),
            httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]}),
        ]
    )
    provider = llm.OpenAICompatibleProvider("key", "https://example.test/v1",
                                            "free-model", timeout=5, name="openrouter")
    result = provider.generate("parse this", json_mode=True, response_schema=Payload)
    assert result.text == '{"ok": true}'
    assert route.call_count == 2
    retry_body = json.loads(route.calls.last.request.content)
    assert "response_format" not in retry_body


@respx.mock
def test_openai_compatible_does_not_retry_hard_failures():
    route = respx.post("https://example.test/v1/chat/completions").mock(
        return_value=httpx.Response(401, text="invalid key")
    )
    provider = llm.OpenAICompatibleProvider("key", "https://example.test/v1",
                                            "test-model", timeout=5, name="custom")
    with pytest.raises(LLMUnavailableError) as excinfo:
        provider.generate("parse this")
    assert not isinstance(excinfo.value, LLMOverloadedError)
    assert route.call_count == 1
