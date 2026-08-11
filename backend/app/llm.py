"""OpenRouter: one gateway, many models.

Everything that talks to a language model goes through here — chat and image
description alike — so the rest of the app never knows or cares which provider
is behind the current model.

OpenRouter speaks the OpenAI chat-completions format, so the official `openai`
client works against it with a different `base_url`. That buys typed errors and
automatic retries rather than hand-rolling both over httpx.

Only the *reasoning* model is swappable. Embeddings stay local (all-MiniLM-L6-v2
via Chroma) and speech-to-text stays local (Whisper), because the point of
MERROR is that your archive does not leave the machine.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx
import openai

from app.config import get_settings, require_key

logger = logging.getLogger("merror.llm")

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODELS_URL = f"{OPENROUTER_BASE_URL}/models"

# Sent on every request. OpenRouter uses these to attribute traffic on its
# public leaderboards; they are optional and identify the app, not the user.
ATTRIBUTION_HEADERS = {
    "HTTP-Referer": "http://localhost:3000",
    "X-Title": "MERROR",
}

MODEL_LIST_TIMEOUT_SECONDS = 20.0


class LLMError(RuntimeError):
    """The model could not be reached, or would not answer."""


class ModelRefusedError(LLMError):
    """The model declined to answer.

    Providers signal this inconsistently — some return a `refusal` field, some
    a content filter finish reason, some just an apologetic message. Only the
    first two are detectable, and this covers those.
    """


@dataclass(frozen=True)
class ModelInfo:
    """One model offered by OpenRouter."""

    id: str
    name: str
    context_length: int
    supports_images: bool
    prompt_price: float
    completion_price: float

    @property
    def is_free(self) -> bool:
        return self.prompt_price == 0.0 and self.completion_price == 0.0


def get_client() -> openai.OpenAI:
    """An OpenAI-compatible client pointed at OpenRouter."""
    return openai.OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=require_key("OPENROUTER_API_KEY"),
        default_headers=ATTRIBUTION_HEADERS,
    )


def _describe_error(exc: Exception) -> str:
    """Turn an SDK exception into something a person can act on."""
    if isinstance(exc, openai.AuthenticationError):
        return "OpenRouter rejected the API key. Check OPENROUTER_API_KEY."
    if isinstance(exc, openai.PermissionDeniedError):
        return (
            "OpenRouter refused this model. Your account may not have access, "
            "or the model may require added credit."
        )
    if isinstance(exc, openai.NotFoundError):
        return (
            "That model id was not found on OpenRouter. Check it against the "
            "model list — ids look like 'anthropic/claude-opus-4.5'."
        )
    if isinstance(exc, openai.RateLimitError):
        return "OpenRouter rate limit or credit limit reached."
    if isinstance(exc, openai.APIStatusError):
        return f"OpenRouter returned {exc.status_code}."
    if isinstance(exc, openai.APITimeoutError):
        return "OpenRouter timed out. Try a smaller request or a faster model."
    if isinstance(exc, openai.APIConnectionError):
        return "Could not reach OpenRouter. Check your connection."
    return f"Unexpected error talking to OpenRouter: {exc}"


def complete(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float | None = None,
) -> str:
    """Send a chat completion and return the reply text.

    `model` overrides the configured default, which is how the UI switches
    models per conversation without a restart.
    """
    settings = get_settings()
    chosen = (model or settings.openrouter_model).strip()

    request: dict[str, Any] = {
        "model": chosen,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    # Left unset by default: reasoning models on OpenRouter reject or ignore
    # temperature, and the gateway's own default is the safer choice.
    if temperature is not None:
        request["temperature"] = temperature

    try:
        response = get_client().chat.completions.create(**request)
    except openai.OpenAIError as exc:
        raise LLMError(_describe_error(exc)) from exc

    if not response.choices:
        raise LLMError(f"{chosen} returned no response.")

    choice = response.choices[0]
    message = choice.message

    # Some providers surface a policy decline in a dedicated field rather than
    # as an error, so it arrives looking like a perfectly normal 200.
    refusal = getattr(message, "refusal", None)
    if refusal:
        logger.warning("%s refused: %s", chosen, refusal)
        raise ModelRefusedError(f"{chosen} declined to answer: {refusal}")

    if choice.finish_reason == "content_filter":
        raise ModelRefusedError(f"{chosen} declined to answer this request.")

    text = (message.content or "").strip()
    if not text:
        raise LLMError(f"{chosen} returned an empty response.")

    if choice.finish_reason == "length":
        logger.warning("Reply from %s was truncated at the token limit", chosen)

    usage = getattr(response, "usage", None)
    logger.info(
        "%s replied (%d chars, %s prompt / %s completion tokens)",
        chosen,
        len(text),
        getattr(usage, "prompt_tokens", "?"),
        getattr(usage, "completion_tokens", "?"),
    )
    return text


def _parse_model(raw: dict[str, Any]) -> ModelInfo | None:
    """Read one entry from OpenRouter's model list, skipping malformed ones."""
    model_id = raw.get("id")
    if not model_id:
        return None

    architecture = raw.get("architecture") or {}
    # OpenRouter renamed this field; accept both so a gateway-side change does
    # not silently mark every model as text-only.
    modalities = (
        architecture.get("input_modalities")
        or architecture.get("modality", "")
        or []
    )
    if isinstance(modalities, str):
        # The legacy form encodes both directions as "text+image->text"; only
        # the part before the arrow describes what the model accepts.
        inputs = modalities.split("->")[0]
        modalities = [part.strip() for part in inputs.split("+") if part.strip()]

    pricing = raw.get("pricing") or {}

    def price(key: str) -> float:
        try:
            return float(pricing.get(key) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    return ModelInfo(
        id=str(model_id),
        name=str(raw.get("name") or model_id),
        context_length=int(raw.get("context_length") or 0),
        supports_images="image" in modalities,
        prompt_price=price("prompt"),
        completion_price=price("completion"),
    )


def list_models() -> list[ModelInfo]:
    """Every model OpenRouter currently offers, cheapest-looking first.

    Fetched live rather than hardcoded: OpenRouter's catalogue changes weekly,
    and a baked-in list would be wrong within a month.
    """
    try:
        response = httpx.get(
            OPENROUTER_MODELS_URL,
            headers={"Authorization": f"Bearer {require_key('OPENROUTER_API_KEY')}"},
            timeout=MODEL_LIST_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise LLMError(f"Could not reach OpenRouter: {exc}") from exc

    if response.status_code == 401:
        raise LLMError("OpenRouter rejected the API key. Check OPENROUTER_API_KEY.")
    if response.status_code >= 400:
        raise LLMError(f"OpenRouter returned {response.status_code} listing models.")

    try:
        payload = response.json().get("data") or []
    except ValueError as exc:
        raise LLMError("OpenRouter returned an unreadable model list.") from exc

    models = [parsed for raw in payload if (parsed := _parse_model(raw)) is not None]
    models.sort(key=lambda m: m.id)

    logger.info("OpenRouter offers %d models", len(models))
    return models
