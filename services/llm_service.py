"""Central LLM service.

All model calls go through this module. Providers are pluggable: Gemini speaks
its native API, everything else uses the OpenAI ``/chat/completions`` shape, so
one set of environment variables covers OpenAI, Groq, OpenRouter, DeepSeek,
Mistral, Cerebras, Z.ai, a local Ollama, or any custom endpoint.

Two rules keep this module predictable:

* every request has a hard timeout, so the UI can never hang on a stalled call;
* capacity errors (HTTP 429/5xx) are retried with a real backoff and surfaced as
  ``LLMOverloadedError`` instead of being mistaken for a broken configuration.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from string import Template
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError
from tenacity import (
    Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter,
)

from config import PROJECT_ROOT, get_settings
from core.exceptions import (
    LLMOverloadedError, LLMResponseError, LLMUnavailableError,
)
from core.logging_config import get_logger

logger = get_logger("llm")

PROMPTS_DIR = PROJECT_ROOT / "prompts"
T = TypeVar("T", bound=BaseModel)

# Rough public list prices (USD per 1M input/output tokens) for cost awareness only.
COST_TABLE = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-1.5-flash": (0.075, 0.30),
}

# Retry policy for capacity errors. ``_RETRY_INITIAL_WAIT`` is module level so
# tests can zero it out without waiting.
_RETRY_INITIAL_WAIT = 2.0
_RETRY_MAX_WAIT = 30.0
_RETRY_ATTEMPTS = 3

_OVERLOAD_HINTS = re.compile(
    r"\b(429|500|502|503|504)\b|UNAVAILABLE|RESOURCE_EXHAUSTED|high demand|"
    r"overloaded|rate limit|too many requests|temporarily unavailable",
    re.IGNORECASE,
)


@dataclass
class LLMResponse:
    text: str
    model: str = ""
    prompt_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0


def render_prompt(name: str, **context: Any) -> str:
    """Load a prompt template and substitute ``$placeholders`` safely."""
    path = PROMPTS_DIR / f"{name}.txt"
    if not path.exists():
        raise LLMResponseError(f"Prompt template '{name}' not found")
    template = Template(path.read_text(encoding="utf-8"))
    values = {k: (v if isinstance(v, str) else json.dumps(v, indent=2, ensure_ascii=False))
              for k, v in context.items()}
    return template.safe_substitute(**values)


def extract_json_block(text: str) -> dict:
    """Pull the first JSON object out of a model response."""
    if not text or not text.strip():
        raise LLMResponseError("The model returned an empty response")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
        raise LLMResponseError("The model returned JSON that is not an object")
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end <= start:
        raise LLMResponseError("No JSON object found in the model response")
    try:
        parsed = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError as exc:
        raise LLMResponseError(f"Invalid JSON from model: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise LLMResponseError("The model returned JSON that is not an object")
    return parsed


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _retrying() -> Retrying:
    """Retry only capacity errors; real failures propagate immediately."""
    return Retrying(
        retry=retry_if_exception_type(LLMOverloadedError),
        stop=stop_after_attempt(_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=_RETRY_INITIAL_WAIT, max=_RETRY_MAX_WAIT),
        reraise=True,
    )


def _status_code(exc: Exception) -> int | None:
    for attribute in ("code", "status_code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def classify_provider_error(exc: Exception, *, provider: str = "LLM") -> Exception:
    """Map a provider exception onto the domain errors callers understand."""
    status = _status_code(exc)
    message = str(exc).strip() or type(exc).__name__
    if "API_KEY_INVALID" in message or "API key not valid" in message:
        return LLMUnavailableError(
            f"{provider} rejected the API key. Check the key configured in .env "
            "(GEMINI_API_KEY, or LLM_API_KEY for another provider).",
            details={"status": status, "provider": provider, "reason": "api_key_invalid"},
        )
    if status in (429, 500, 502, 503, 504) or _OVERLOAD_HINTS.search(message):
        return LLMOverloadedError(
            f"{provider} is temporarily rate limited or at capacity ({message[:200]}). "
            "Retried with backoff; try again in a minute.",
            details={"status": status, "provider": provider},
        )
    return LLMUnavailableError(f"{provider} request failed: {message[:300]}",
                               details={"status": status, "provider": provider})


def thinking_config_for(model: str):
    """Return a thinking config appropriate for the model family.

    Gemini 2.5 accepts ``thinking_budget`` and 0 disables thinking. Gemini 3.5+
    rejects that field and requires ``thinking_level`` instead, so guessing
    wrong here turns a slow call into a hard 400.
    """
    from google.genai import types

    match = re.search(r"gemini-(\d+)(?:\.(\d+))?", (model or "").lower())
    if not match:
        return None
    major, minor = int(match.group(1)), int(match.group(2) or 0)
    if (major, minor) >= (3, 5):
        return types.ThinkingConfig(thinking_level="MINIMAL")
    if (major, minor) >= (2, 5):
        return types.ThinkingConfig(thinking_budget=0)
    return None


def json_schema_for(schema: type[BaseModel] | None) -> dict | None:
    if schema is None:
        return None
    try:
        return schema.model_json_schema()
    except Exception:  # pragma: no cover - defensive
        return None


def _format_rejected(text: str) -> bool:
    """Some free/limited models do not implement OpenAI JSON mode."""
    message = (text or "").lower()
    return any(term in message for term in
               ("response_format", "json mode", "structured output"))


def _is_unsupported_option(exc: Exception) -> bool:
    """A 400 that names one of our optional knobs means: retry without it."""
    if _status_code(exc) not in (400, 422):
        return False
    message = str(exc).lower()
    return any(term in message for term in ("thinking", "schema", "response_json"))


def _estimate_cost(model: str, prompt_tokens: int, output_tokens: int) -> float:
    price_in, price_out = COST_TABLE.get(model, (0.0, 0.0))
    return round((prompt_tokens / 1_000_000) * price_in
                 + (output_tokens / 1_000_000) * price_out, 6)


class LLMProvider:
    """Interface every LLM provider must implement."""

    name = "abstract"
    model = ""

    @property
    def available(self) -> bool:  # pragma: no cover - interface
        return False

    def generate(self, prompt: str, *, system: str | None = None,
                 json_mode: bool = True, temperature: float | None = None,
                 response_schema: type[BaseModel] | None = None) -> LLMResponse:
        raise NotImplementedError


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str, timeout: float = 45) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._client = None

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _get_client(self):
        if self._client is None:
            from google import genai  # imported lazily so the app runs without it
            from google.genai import types

            # The SDK defaults to no timeout at all, which lets one stalled
            # request block the Streamlit script forever.
            self._client = genai.Client(
                api_key=self.api_key,
                http_options=types.HttpOptions(timeout=int(self.timeout * 1000)),
            )
        return self._client

    def generate(self, prompt: str, *, system: str | None = None,
                 json_mode: bool = True, temperature: float | None = None,
                 response_schema: type[BaseModel] | None = None) -> LLMResponse:
        for attempt in _retrying():
            with attempt:
                return self._generate_once(prompt, system, json_mode, temperature,
                                           response_schema)
        raise LLMUnavailableError("Gemini request failed")  # pragma: no cover

    def _generate_once(self, prompt: str, system: str | None, json_mode: bool,
                       temperature: float | None,
                       response_schema: type[BaseModel] | None) -> LLMResponse:
        from google.genai import types

        settings = get_settings()
        config_kwargs: dict[str, Any] = {
            "temperature": settings.llm_temperature if temperature is None else temperature,
            "response_mime_type": "application/json" if json_mode else "text/plain",
            "system_instruction": system,
            "max_output_tokens": settings.llm_max_output_tokens,
        }
        thinking = thinking_config_for(self.model)
        if thinking is not None:
            config_kwargs["thinking_config"] = thinking
        schema = json_schema_for(response_schema) if json_mode else None
        if schema is not None:
            config_kwargs["response_json_schema"] = schema

        client = self._get_client()
        response = None
        for strip_optional in (False, True):
            try:
                response = client.models.generate_content(
                    model=self.model, contents=prompt,
                    config=types.GenerateContentConfig(**config_kwargs),
                )
                break
            except Exception as exc:
                if not strip_optional and _is_unsupported_option(exc):
                    logger.info("Retrying without thinking/schema options: %s",
                                str(exc)[:160])
                    config_kwargs.pop("thinking_config", None)
                    config_kwargs.pop("response_json_schema", None)
                    continue
                logger.warning("Gemini request failed: %s", str(exc)[:300])
                raise classify_provider_error(exc, provider="Gemini") from exc

        text = getattr(response, "text", None) or ""
        usage = getattr(response, "usage_metadata", None)
        prompt_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
        output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
        cost = _estimate_cost(self.model, prompt_tokens, output_tokens)
        logger.info("Gemini(%s) ok: %s prompt / %s output tokens, ~$%.4f",
                    self.model, prompt_tokens, output_tokens, cost)
        return LLMResponse(text=text, model=self.model, prompt_tokens=prompt_tokens,
                           output_tokens=output_tokens, estimated_cost_usd=cost)


class OpenAICompatibleProvider(LLMProvider):
    """Any endpoint implementing ``POST {base_url}/chat/completions``."""

    def __init__(self, api_key: str, base_url: str, model: str,
                 timeout: float = 45, name: str = "openai_compatible") -> None:
        self.api_key = api_key
        self.base_url = (base_url or "").rstrip("/")
        self.model = model
        self.timeout = timeout
        self.name = name

    @property
    def available(self) -> bool:
        return bool(self.model) and (bool(self.api_key) or self.name == "ollama")

    def generate(self, prompt: str, *, system: str | None = None,
                 json_mode: bool = True, temperature: float | None = None,
                 response_schema: type[BaseModel] | None = None) -> LLMResponse:
        for attempt in _retrying():
            with attempt:
                return self._generate_once(prompt, system, json_mode, temperature,
                                           response_schema)
        raise LLMUnavailableError(f"{self.name} request failed")  # pragma: no cover

    def _generate_once(self, prompt: str, system: str | None, json_mode: bool,
                       temperature: float | None,
                       response_schema: type[BaseModel] | None) -> LLMResponse:
        if not self.base_url:
            raise LLMUnavailableError(
                "No LLM endpoint configured. Set LLM_BASE_URL (or pick a provider "
                "preset such as groq, openrouter or openai)."
            )
        settings = get_settings()
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        # The prompt template already describes the JSON shape. Repeating the
        # full schema here inflates the prompt (and Groq counts max_tokens
        # against the per-minute budget), so it is deliberately not injected.
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": settings.llm_temperature if temperature is None else temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if settings.llm_max_output_tokens:
            payload["max_tokens"] = settings.llm_max_output_tokens
        if settings.llm_reasoning_effort:
            # Supported by Groq and OpenRouter; ignored by strict providers.
            payload["reasoning_effort"] = settings.llm_reasoning_effort

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        response = None
        try:
            with httpx.Client(timeout=self.timeout) as client:
                for strip_format in (False, True):
                    body = dict(payload)
                    if strip_format:
                        body.pop("response_format", None)
                    response = client.post(f"{self.base_url}/chat/completions",
                                           json=body, headers=headers)
                    if (not strip_format and response.status_code in (400, 422)
                            and _format_rejected(response.text)):
                        logger.info("%s rejected response_format; retrying without it",
                                    self.name)
                        continue
                    break
        except httpx.TimeoutException as exc:
            raise LLMOverloadedError(
                f"{self.name} did not answer within {self.timeout:.0f}s. "
                "Try again, or lower LLM_MAX_OUTPUT_TOKENS.",
                details={"provider": self.name},
            ) from exc
        except httpx.HTTPError as exc:
            raise classify_provider_error(exc, provider=self.name) from exc

        if response.status_code >= 400:
            raise classify_provider_error(
                httpx.HTTPStatusError(
                    f"{response.status_code} {response.reason_phrase}: "
                    f"{response.text[:300]}",
                    request=response.request or httpx.Request(
                        "POST", f"{self.base_url}/chat/completions"),
                    response=response,
                ),
                provider=self.name,
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise LLMResponseError(f"{self.name} returned non-JSON: {exc}") from exc

        choices = data.get("choices") or []
        first = (choices[0] or {}) if choices else {}
        message = first.get("message") or {}
        text = message.get("content") or ""
        usage = data.get("usage") or {}
        if not text.strip():
            details = usage.get("completion_tokens_details") or {}
            reasoning_tokens = int(details.get("reasoning_tokens") or 0)
            if reasoning_tokens or message.get("reasoning"):
                raise LLMResponseError(
                    f"{self.name} ({self.model}) spent its entire output budget on reasoning "
                    f"({reasoning_tokens:,} tokens) and returned no answer. Choose a "
                    "non-reasoning model, or raise LLM_MAX_OUTPUT_TOKENS."
                )
            raise LLMResponseError(
                f"{self.name} returned an empty response"
                + (f" (finish_reason: {first.get('finish_reason')})"
                   if first.get("finish_reason") else "")
            )

        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)
        cost = _estimate_cost(self.model, prompt_tokens, output_tokens)
        logger.info("%s(%s) ok: %s prompt / %s output tokens, ~$%.4f",
                    self.name, self.model, prompt_tokens, output_tokens, cost)
        return LLMResponse(text=text, model=self.model, prompt_tokens=prompt_tokens,
                           output_tokens=output_tokens, estimated_cost_usd=cost)


class NullProvider(LLMProvider):
    """Used when no provider is configured. Callers fall back to degraded mode."""

    name = "none"
    model = ""

    @property
    def available(self) -> bool:
        return False

    def generate(self, prompt: str, *, system: str | None = None,
                 json_mode: bool = True, temperature: float | None = None,
                 response_schema: type[BaseModel] | None = None) -> LLMResponse:
        raise LLMUnavailableError(
            "No LLM is configured. Add GEMINI_API_KEY (or LLM_PROVIDER + LLM_API_KEY) "
            "in Settings or .env to enable AI features."
        )


class LLMService:
    def __init__(self, provider: LLMProvider | None = None) -> None:
        self.provider = provider or _default_provider()
        self.last_usage: LLMResponse | None = None

    @property
    def available(self) -> bool:
        return bool(self.provider and self.provider.available)

    def generate_text(self, prompt: str, *, system: str | None = None,
                      temperature: float | None = None) -> str:
        if not self.available:
            raise LLMUnavailableError(
                "No LLM is configured. Add GEMINI_API_KEY (or LLM_PROVIDER + LLM_API_KEY) "
                "in Settings or .env to enable AI features."
            )
        response = self.provider.generate(prompt, system=system, json_mode=False,
                                          temperature=temperature)
        self.last_usage = response
        return response.text

    def generate_json(self, prompt: str, schema: type[T], *, system: str | None = None,
                      attempts: int | None = None, temperature: float | None = None) -> T:
        """Generate and validate structured output, retrying only on bad JSON.

        Capacity errors are not retried here: the provider already backs off,
        and repeating the whole prompt would only burn more quota.
        """
        if not self.available:
            raise LLMUnavailableError(
                "No LLM is configured. Add GEMINI_API_KEY (or LLM_PROVIDER + LLM_API_KEY) "
                "in Settings or .env to enable AI features."
            )
        tries = attempts or max(1, get_settings().llm_max_retries + 1)
        last_error: Exception | None = None
        current_prompt = prompt
        for attempt in range(1, tries + 1):
            response = self.provider.generate(current_prompt, system=system, json_mode=True,
                                              temperature=temperature,
                                              response_schema=schema)
            self.last_usage = response
            try:
                payload = extract_json_block(response.text)
                return schema.model_validate(payload)
            except (LLMResponseError, ValidationError) as exc:
                last_error = exc
                logger.warning("LLM JSON attempt %s/%s failed: %s", attempt, tries, exc)
                current_prompt = (
                    prompt
                    + "\n\nYour previous answer was rejected because it did not match the required "
                    f"JSON schema ({str(exc)[:400]}). Return ONLY valid JSON that exactly matches "
                    "the schema, with no commentary and no markdown fences."
                )
        raise LLMResponseError(f"Model did not return valid structured JSON: {last_error}")

    def prompt_json(self, prompt_name: str, schema: type[T], *, attempts: int | None = None,
                    **context: Any) -> T:
        return self.generate_json(render_prompt(prompt_name, **context), schema, attempts=attempts)

    def prompt_text(self, prompt_name: str, **context: Any) -> str:
        return self.generate_text(render_prompt(prompt_name, **context))

    def describe(self) -> dict:
        return {
            "provider": self.provider.name if self.provider else "none",
            "model": getattr(self.provider, "model", ""),
            "available": self.available,
            "last_usage": (
                {
                    "prompt_tokens": self.last_usage.prompt_tokens,
                    "output_tokens": self.last_usage.output_tokens,
                    "estimated_cost_usd": self.last_usage.estimated_cost_usd,
                }
                if self.last_usage else None
            ),
        }


def _default_provider() -> LLMProvider:
    settings = get_settings()
    if not settings.llm_available:
        return NullProvider()
    if settings.llm_provider == "gemini":
        return GeminiProvider(settings.gemini_api_key, settings.active_model,
                              timeout=settings.llm_timeout_seconds)
    return OpenAICompatibleProvider(
        settings.llm_api_key, settings.llm_endpoint, settings.active_model,
        timeout=settings.llm_timeout_seconds, name=settings.llm_provider,
    )


_service: LLMService | None = None


def get_llm_service() -> LLMService:
    global _service
    if _service is None:
        _service = LLMService()
    return _service


def configure_llm(provider: LLMProvider | None) -> LLMService:
    """Inject a provider (tests, or a future alternative provider)."""
    global _service
    _service = LLMService(provider)
    return _service


def reset_llm() -> None:
    global _service
    _service = None
