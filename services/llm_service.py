"""Central LLM service.

All model calls go through this module. The provider is replaceable: any
object implementing ``generate`` can be injected, so tests never call the
network and a future provider can be added without touching callers.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from config import PROJECT_ROOT, get_settings
from core.exceptions import LLMResponseError, LLMUnavailableError
from core.logging_config import get_logger

logger = get_logger("llm")

PROMPTS_DIR = PROJECT_ROOT / "prompts"
T = TypeVar("T", bound=BaseModel)

# Rough public list prices (USD per 1M tokens) for cost awareness only.
COST_TABLE = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-1.5-flash": (0.075, 0.30),
}


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


class LLMProvider:
    """Interface every LLM provider must implement."""

    name = "abstract"

    @property
    def available(self) -> bool:  # pragma: no cover - interface
        return False

    def generate(self, prompt: str, *, system: str | None = None,
                 json_mode: bool = True, temperature: float | None = None) -> LLMResponse:
        raise NotImplementedError


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str, timeout: int = 60) -> None:
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

            self._client = genai.Client(api_key=self.api_key)
        return self._client

    @retry(
        retry=retry_if_exception_type((LLMUnavailableError,)),
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=8),
        reraise=True,
    )
    def generate(self, prompt: str, *, system: str | None = None,
                 json_mode: bool = True, temperature: float | None = None) -> LLMResponse:
        from google.genai import types

        try:
            client = self._get_client()
            config = types.GenerateContentConfig(
                temperature=get_settings().llm_temperature if temperature is None else temperature,
                response_mime_type="application/json" if json_mode else "text/plain",
                system_instruction=system,
            )
            response = client.models.generate_content(model=self.model, contents=prompt, config=config)
        except Exception as exc:  # network, auth, quota
            message = str(exc)
            logger.warning("Gemini request failed: %s", message)
            raise LLMUnavailableError(f"Gemini request failed: {message}") from exc

        text = getattr(response, "text", None) or ""
        usage = getattr(response, "usage_metadata", None)
        prompt_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
        output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
        price_in, price_out = COST_TABLE.get(self.model, (0.0, 0.0))
        cost = (prompt_tokens / 1_000_000) * price_in + (output_tokens / 1_000_000) * price_out
        logger.info(
            "Gemini(%s) ok: %s prompt / %s output tokens, ~$%.4f",
            self.model, prompt_tokens, output_tokens, cost,
        )
        return LLMResponse(text=text, model=self.model, prompt_tokens=prompt_tokens,
                           output_tokens=output_tokens, estimated_cost_usd=round(cost, 6))


class NullProvider(LLMProvider):
    """Used when no API key is configured. Callers fall back to degraded mode."""

    name = "none"

    @property
    def available(self) -> bool:
        return False

    def generate(self, prompt: str, *, system: str | None = None,
                 json_mode: bool = True, temperature: float | None = None) -> LLMResponse:
        raise LLMUnavailableError(
            "No LLM is configured. Add GEMINI_API_KEY in Settings or .env to enable AI features."
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
                "No LLM is configured. Add GEMINI_API_KEY in Settings or .env to enable AI features."
            )
        response = self.provider.generate(prompt, system=system, json_mode=False, temperature=temperature)
        self.last_usage = response
        return response.text

    def generate_json(self, prompt: str, schema: type[T], *, system: str | None = None,
                      attempts: int | None = None, temperature: float | None = None) -> T:
        """Generate and validate structured output, retrying on invalid JSON."""
        if not self.available:
            raise LLMUnavailableError(
                "No LLM is configured. Add GEMINI_API_KEY in Settings or .env to enable AI features."
            )
        tries = attempts or max(1, get_settings().llm_max_retries + 1)
        last_error: Exception | None = None
        current_prompt = prompt
        for attempt in range(1, tries + 1):
            response = self.provider.generate(current_prompt, system=system, json_mode=True,
                                              temperature=temperature)
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
                    f"JSON schema ({exc}). Return ONLY valid JSON that exactly matches the schema, "
                    "with no commentary and no markdown fences."
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
    if settings.llm_available:
        return GeminiProvider(settings.gemini_api_key, settings.gemini_model,
                              timeout=settings.http_timeout_seconds * 3)
    return NullProvider()


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
