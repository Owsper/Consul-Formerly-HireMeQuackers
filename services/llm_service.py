"""Central LLM service.

All model calls go through this module. The app routes each kind of work to a
primary model and an ordered fallback chain: Gemini handles extraction and
high-stakes CV reasoning, Groq handles high-volume drafting and planning, and
every provider uses the OpenAI ``/chat/completions`` shape. That also covers
OpenAI, OpenRouter, DeepSeek, Mistral, Cerebras, Z.ai, a local Ollama, or any
custom endpoint.

Two rules keep this module predictable:

* every request has a hard timeout, so the UI can never hang on a stalled call;
* capacity errors (HTTP 429/5xx) are retried with a real backoff and surfaced as
  ``LLMOverloadedError`` instead of being mistaken for a broken configuration.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from string import Template
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError
from tenacity import (
    Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter,
)

from config import LLMRoute, PROJECT_ROOT, get_settings
from core.exceptions import (
    LLMOverloadedError, LLMResponseError, LLMUnavailableError,
)
from core.logging_config import get_logger

logger = get_logger("llm")

PROMPTS_DIR = PROJECT_ROOT / "prompts"
T = TypeVar("T", bound=BaseModel)

# Rough public list prices (USD per 1M input/output tokens) for cost awareness only.
# Provider pricing changes frequently; unknown models report zero instead of a
# stale estimate.
COST_TABLE: dict[str, tuple[float, float]] = {}

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
            "(GROQ_API_KEY and/or GEMINI_API_KEY, or LLM_API_KEY for another provider).",
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


def _format_rejected(text: str) -> bool:
    """Some free/limited models do not implement OpenAI JSON mode."""
    message = (text or "").lower()
    return any(term in message for term in
               ("response_format", "json mode", "structured output"))


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


class OpenAICompatibleProvider(LLMProvider):
    """Any endpoint implementing ``POST {base_url}/chat/completions``."""

    def __init__(self, api_key: str, base_url: str, model: str,
                 timeout: float = 45, name: str = "openai_compatible",
                 max_output_tokens: int | None = None,
                 reasoning_effort: str | None = None,
                 max_prompt_chars: int = 0) -> None:
        self.api_key = api_key
        self.base_url = (base_url or "").rstrip("/")
        self.model = model
        self.timeout = timeout
        self.name = name
        self.max_output_tokens = max_output_tokens
        self.reasoning_effort = reasoning_effort
        self.max_prompt_chars = max_prompt_chars

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
        output_cap = (self.max_output_tokens if self.max_output_tokens is not None
                      else settings.llm_max_output_tokens)
        if output_cap:
            payload["max_tokens"] = (
                min(output_cap, settings.llm_max_output_tokens)
                if settings.llm_max_output_tokens else output_cap
            )
        effort = (self.reasoning_effort if self.reasoning_effort is not None
                  else settings.llm_reasoning_effort)
        if effort:
            # Supported by Groq and OpenRouter; ignored by strict providers.
            payload["reasoning_effort"] = effort

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
            "No LLM is configured. Add GROQ_API_KEY and/or GEMINI_API_KEY "
            "(or LLM_PROVIDER + LLM_API_KEY) in Settings or .env to enable AI features."
        )


class LLMService:
    """Automatic, task-aware LLM routing with ordered provider fallback.

    Callers name the *kind* of work (``extraction``, ``reasoning``,
    ``writing``, ``planning`` or ``utility``); they never choose a provider or
    model. Each route has a primary and fallbacks, so a free-tier rate limit,
    an outage or a bad JSON response degrades to the next model instead of
    breaking the user's workflow.

    A short in-process cooldown prevents a provider that just returned 429 from
    being hammered by the next request. Keys and limits are per provider, so
    the Groq and Gemini quotas remain independent pools.
    """

    def __init__(self, provider: LLMProvider | None = None, *,
                 routes: dict[str, list[LLMProvider]] | None = None,
                 cooldown_seconds: int | None = None) -> None:
        self._fixed_provider = provider
        if provider is not None:
            self.routes: dict[str, list[LLMProvider]] = {}
        elif routes is not None:
            self.routes = routes
        else:
            self.routes = _build_task_routes(get_settings())
        self.provider = provider or self._primary_provider()
        self.last_usage: LLMResponse | None = None
        self.last_provider: str | None = None
        self._cooldown_until: dict[str, datetime] = {}
        self._cooldown_seconds = (cooldown_seconds if cooldown_seconds is not None
                                  else get_settings().llm_cooldown_seconds)

    @property
    def available(self) -> bool:
        if self._fixed_provider is not None:
            return bool(self._fixed_provider.available)
        return any(provider.available for providers in self.routes.values()
                   for provider in providers)

    @staticmethod
    def _provider_key(provider: LLMProvider) -> str:
        return f"{provider.name}:{provider.model}"

    def _primary_provider(self) -> LLMProvider:
        for task in ("extraction", "reasoning", "writing", "planning", "utility"):
            for provider in self.routes.get(task, []):
                if provider.available:
                    return provider
        return NullProvider()

    @staticmethod
    def _prompt_fits(provider: LLMProvider, prompt: str) -> bool:
        limit = getattr(provider, "max_prompt_chars", 0)
        return not limit or len(prompt) <= limit

    def _providers_for(self, task: str) -> list[LLMProvider]:
        if self._fixed_provider is not None:
            if not self._fixed_provider.available:
                raise LLMUnavailableError(
                    "No LLM is configured. Add GROQ_API_KEY and/or GEMINI_API_KEY "
                    "in Settings or .env to enable AI features."
                )
            return [self._fixed_provider]

        providers = self.routes.get(task) or self.routes.get("utility") or []
        now = datetime.now(timezone.utc)
        active = [p for p in providers
                  if p.available and self._cooldown_until.get(self._provider_key(p), now) <= now]
        if active:
            return active
        if not self.available:
            raise LLMUnavailableError(
                "No LLM is configured. Add GROQ_API_KEY and/or GEMINI_API_KEY "
                "in Settings or .env to enable AI features."
            )
        retry_at = min(self._cooldown_until.values(), default=now)
        wait = max(1, int((retry_at - now).total_seconds()))
        raise LLMOverloadedError(
            f"All LLM providers for {task} are cooling down after rate limits. "
            f"Try again in about {wait}s.",
            details={"task": task, "retry_in_seconds": wait},
        )

    def _mark_failure(self, provider: LLMProvider, exc: Exception) -> None:
        key = self._provider_key(provider)
        if isinstance(exc, LLMOverloadedError):
            seconds = max(1, self._cooldown_seconds)
        elif isinstance(exc, LLMUnavailableError):
            # A bad key or unsupported model needs operator action, not a retry
            # every few minutes. Keep it out of the hot path for longer.
            seconds = max(600, self._cooldown_seconds)
        else:
            return
        self._cooldown_until[key] = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        logger.warning("LLM route %s cooling down for %ss: %s", key, seconds, exc)

    def _record_success(self, provider: LLMProvider, response: LLMResponse) -> None:
        self.last_usage = response
        self.last_provider = provider.name
        self._cooldown_until.pop(self._provider_key(provider), None)

    def generate_text(self, prompt: str, *, system: str | None = None,
                      temperature: float | None = None,
                      task: str = "utility") -> str:
        last_error: Exception | None = None
        for provider in self._providers_for(task):
            if not self._prompt_fits(provider, prompt):
                logger.info("Skipping %s for %s: prompt is %s chars, limit is %s",
                            self._provider_key(provider), task, len(prompt),
                            getattr(provider, "max_prompt_chars", 0))
                last_error = LLMUnavailableError(
                    f"The prompt is too large for {self._provider_key(provider)}'s free "
                    "per-minute budget."
                )
                continue
            try:
                response = provider.generate(prompt, system=system, json_mode=False,
                                             temperature=temperature)
                self._record_success(provider, response)
                return response.text
            except (LLMOverloadedError, LLMUnavailableError) as exc:
                self._mark_failure(provider, exc)
                last_error = exc
                logger.info("LLM %s failed for %s; trying next route: %s",
                            self._provider_key(provider), task, exc)
            except LLMResponseError as exc:
                last_error = exc
                logger.info("LLM %s returned an unusable response for %s; trying next route: %s",
                            self._provider_key(provider), task, exc)
        if last_error:
            raise last_error
        raise LLMUnavailableError("No LLM provider produced a response.")

    def _generate_json_with_provider(self, provider: LLMProvider, prompt: str,
                                     schema: type[T], *, system: str | None,
                                     attempts: int | None,
                                     temperature: float | None) -> T:
        """Schema retries stay on one provider; route fallback is the caller's job."""
        tries = attempts or max(1, get_settings().llm_max_retries + 1)
        last_error: Exception | None = None
        current_prompt = prompt
        for attempt in range(1, tries + 1):
            response = provider.generate(current_prompt, system=system, json_mode=True,
                                         temperature=temperature,
                                         response_schema=schema)
            self._record_success(provider, response)
            try:
                payload = extract_json_block(response.text)
                return schema.model_validate(payload)
            except (LLMResponseError, ValidationError) as exc:
                last_error = exc
                logger.warning("LLM %s JSON attempt %s/%s failed: %s",
                               self._provider_key(provider), attempt, tries, exc)
                current_prompt = (
                    prompt
                    + "\n\nYour previous answer was rejected because it did not match the required "
                    f"JSON schema ({str(exc)[:400]}). Return ONLY valid JSON that exactly matches "
                    "the schema, with no commentary and no markdown fences."
                )
        raise LLMResponseError(
            f"{self._provider_key(provider)} did not return valid structured JSON: {last_error}")

    def generate_json(self, prompt: str, schema: type[T], *, system: str | None = None,
                      attempts: int | None = None, temperature: float | None = None,
                      task: str = "utility") -> T:
        """Generate validated structured output across the task's route.

        Capacity errors are not retried here: the provider already backs off,
        and repeating the whole prompt would only burn more quota. Bad JSON is
        retried on the same provider, then the next provider gets a fresh try.
        """
        last_error: Exception | None = None
        for provider in self._providers_for(task):
            if not self._prompt_fits(provider, prompt):
                logger.info("Skipping %s for %s: prompt is %s chars, limit is %s",
                            self._provider_key(provider), task, len(prompt),
                            getattr(provider, "max_prompt_chars", 0))
                last_error = LLMUnavailableError(
                    f"The prompt is too large for {self._provider_key(provider)}'s free "
                    "per-minute budget."
                )
                continue
            try:
                return self._generate_json_with_provider(
                    provider, prompt, schema, system=system, attempts=attempts,
                    temperature=temperature)
            except (LLMOverloadedError, LLMUnavailableError) as exc:
                self._mark_failure(provider, exc)
                last_error = exc
                logger.info("LLM %s failed for %s; trying next route: %s",
                            self._provider_key(provider), task, exc)
            except LLMResponseError as exc:
                last_error = exc
                logger.info("LLM %s failed structured output for %s; trying next route: %s",
                            self._provider_key(provider), task, exc)
        if last_error:
            raise last_error
        raise LLMUnavailableError("No LLM provider produced a response.")

    def prompt_json(self, prompt_name: str, schema: type[T], *, attempts: int | None = None,
                    task: str = "utility", **context: Any) -> T:
        return self.generate_json(render_prompt(prompt_name, **context), schema,
                                  attempts=attempts, task=task)

    def prompt_text(self, prompt_name: str, *, task: str = "utility",
                    **context: Any) -> str:
        return self.generate_text(render_prompt(prompt_name, **context), task=task)

    def describe(self) -> dict:
        routes = {
            task: [{"provider": p.name, "model": p.model} for p in providers]
            for task, providers in self.routes.items()
        }
        return {
            "provider": self.provider.name if self.provider else "none",
            "model": getattr(self.provider, "model", ""),
            "available": self.available,
            "last_provider": self.last_provider,
            "routes": routes,
            "last_usage": (
                {
                    "prompt_tokens": self.last_usage.prompt_tokens,
                    "output_tokens": self.last_usage.output_tokens,
                    "estimated_cost_usd": self.last_usage.estimated_cost_usd,
                }
                if self.last_usage else None
            ),
        }


def _provider_from_route(route: LLMRoute, settings: Any) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        settings.api_key_for(route.provider),
        settings.endpoint_for(route.provider),
        route.model,
        timeout=settings.llm_timeout_seconds,
        name=route.provider,
        max_output_tokens=route.max_output_tokens,
        reasoning_effort=route.reasoning_effort,
        max_prompt_chars=route.max_prompt_chars,
    )


def _build_task_routes(settings: Any) -> dict[str, list[LLMProvider]]:
    routes: dict[str, list[LLMProvider]] = {}
    for task, specs in settings.llm_routes.items():
        routes[task] = [provider for provider in
                        (_provider_from_route(route, settings) for route in specs)
                        if provider.available]

    # A custom/legacy provider (OpenRouter, OpenAI, Ollama, ...) remains the
    # final fallback so existing single-provider installations keep working.
    legacy = _default_provider()
    if legacy.available:
        for providers in routes.values():
            if not any(p.name == legacy.name and p.model == legacy.model for p in providers):
                providers.append(legacy)
    return routes


def _default_provider() -> LLMProvider:
    settings = get_settings()
    provider = settings.llm_provider
    if not settings.provider_available(provider):
        return NullProvider()
    return OpenAICompatibleProvider(
        settings.api_key_for(provider), settings.endpoint_for(provider),
        settings.active_model, timeout=settings.llm_timeout_seconds, name=provider,
        max_output_tokens=(4096 if provider == "groq" else settings.llm_max_output_tokens),
        reasoning_effort=settings.llm_reasoning_effort,
        max_prompt_chars=(16000 if provider == "groq" else 0),
    )


_service: LLMService | None = None


def get_llm_service() -> LLMService:
    global _service
    if _service is None:
        _service = LLMService()
    return _service


def configure_llm(provider: LLMProvider | None) -> LLMService:
    """Inject a provider (tests) or rebuild the automatic routing table."""
    global _service
    _service = LLMService(provider)
    return _service


def reset_llm() -> None:
    global _service
    _service = None
