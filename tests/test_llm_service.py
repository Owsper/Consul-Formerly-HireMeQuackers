"""Provider selection, retry policy and the OpenAI-compatible client."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from google.genai import types
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


def test_thinking_config_matches_the_model_family():
    # Gemini 3.5+ rejects thinking_budget and requires thinking_level.
    assert llm.thinking_config_for("gemini-3.8-flash") == types.ThinkingConfig(
        thinking_level=types.ThinkingLevel.MINIMAL)
    assert llm.thinking_config_for("gemini-2.5-flash") == types.ThinkingConfig(
        thinking_budget=0)
    assert llm.thinking_config_for("gemini-2.0-flash") is None


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


def test_gemini_provider_gets_the_configured_timeout(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "17")
    config.get_settings.cache_clear()
    provider = llm._default_provider()
    assert isinstance(provider, llm.GeminiProvider)
    assert provider.timeout == 17


def test_no_provider_when_llm_is_disabled(monkeypatch):
    monkeypatch.setenv("LLM_ENABLED", "0")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    config.get_settings.cache_clear()
    assert not llm._default_provider().available


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
