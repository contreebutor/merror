"""Tests for the OpenRouter client layer."""

from dataclasses import dataclass, field

import httpx
import openai
import pytest

from app import llm


# --- Stand-ins for the OpenAI response shape -------------------------------


@dataclass
class FakeMessage:
    content: str | None = ""
    refusal: str | None = None


@dataclass
class FakeChoice:
    message: FakeMessage = field(default_factory=FakeMessage)
    finish_reason: str = "stop"


@dataclass
class FakeUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class FakeCompletion:
    choices: list = field(default_factory=list)
    usage: FakeUsage = field(default_factory=FakeUsage)


class FakeCompletions:
    def __init__(self, response):
        self._response = response
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class FakeClient:
    def __init__(self, response):
        self.chat = type("Chat", (), {"completions": FakeCompletions(response)})()


@pytest.fixture
def fake_llm(monkeypatch):
    """Replace the OpenRouter client with a scripted stand-in."""

    def install(response):
        client = FakeClient(response)
        monkeypatch.setattr(llm, "get_client", lambda: client)
        return client

    return install


def reply(text: str) -> FakeCompletion:
    return FakeCompletion(choices=[FakeChoice(message=FakeMessage(content=text))])


def api_error(cls, status_code: int = 400):
    """Build a real SDK exception, since the code branches on its type."""
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    response = httpx.Response(status_code, request=request, json={"error": {"message": "x"}})
    return cls("boom", response=response, body=None)


# --- Completions -----------------------------------------------------------


def test_complete_returns_text(fake_llm):
    fake_llm(reply("You have written about this before."))
    assert llm.complete([{"role": "user", "content": "hi"}]) == (
        "You have written about this before."
    )


def test_complete_uses_the_configured_model_by_default(fake_llm):
    client = fake_llm(reply("ok"))
    llm.complete([{"role": "user", "content": "hi"}])
    assert client.chat.completions.calls[0]["model"] == "anthropic/claude-sonnet-4.5"


def test_complete_honours_a_per_request_model(fake_llm):
    """Switching models must not require a restart."""
    client = fake_llm(reply("ok"))
    llm.complete([{"role": "user", "content": "hi"}], model="openai/gpt-4o")
    assert client.chat.completions.calls[0]["model"] == "openai/gpt-4o"


def test_temperature_is_omitted_unless_asked_for(fake_llm):
    """Reasoning models reject temperature; the gateway default is safer."""
    client = fake_llm(reply("ok"))
    llm.complete([{"role": "user", "content": "hi"}])
    assert "temperature" not in client.chat.completions.calls[0]

    llm.complete([{"role": "user", "content": "hi"}], temperature=0.7)
    assert client.chat.completions.calls[1]["temperature"] == 0.7


def test_refusal_field_is_detected(fake_llm):
    """A policy decline arrives as a normal 200 with a refusal field."""
    fake_llm(
        FakeCompletion(
            choices=[FakeChoice(message=FakeMessage(content=None, refusal="Not this one."))]
        )
    )
    with pytest.raises(llm.ModelRefusedError, match="Not this one"):
        llm.complete([{"role": "user", "content": "hi"}])


def test_content_filter_finish_reason_is_detected(fake_llm):
    fake_llm(
        FakeCompletion(
            choices=[FakeChoice(message=FakeMessage(content=""), finish_reason="content_filter")]
        )
    )
    with pytest.raises(llm.ModelRefusedError):
        llm.complete([{"role": "user", "content": "hi"}])


def test_empty_response_raises(fake_llm):
    fake_llm(FakeCompletion(choices=[]))
    with pytest.raises(llm.LLMError, match="no response"):
        llm.complete([{"role": "user", "content": "hi"}])


def test_blank_content_raises(fake_llm):
    fake_llm(reply("   "))
    with pytest.raises(llm.LLMError, match="empty response"):
        llm.complete([{"role": "user", "content": "hi"}])


@pytest.mark.parametrize(
    "error_class,status,expected",
    [
        (openai.AuthenticationError, 401, "api key"),
        (openai.PermissionDeniedError, 403, "access"),
        (openai.NotFoundError, 404, "model id"),
        (openai.RateLimitError, 429, "rate limit"),
    ],
)
def test_errors_become_actionable_messages(fake_llm, error_class, status, expected):
    fake_llm(api_error(error_class, status))
    with pytest.raises(llm.LLMError) as exc:
        llm.complete([{"role": "user", "content": "hi"}])
    assert expected in str(exc.value).lower()


def test_unknown_model_message_shows_the_id_format(fake_llm):
    """The most likely mistake is a bare model name with no provider prefix."""
    fake_llm(api_error(openai.NotFoundError, 404))
    with pytest.raises(llm.LLMError) as exc:
        llm.complete([{"role": "user", "content": "hi"}], model="claude-opus-5")
    assert "anthropic/" in str(exc.value)


# --- Model listing ---------------------------------------------------------


def fake_models_response(payload: dict, status_code: int = 200):
    def getter(*args, **kwargs):
        request = httpx.Request("GET", llm.OPENROUTER_MODELS_URL)
        return httpx.Response(status_code, request=request, json=payload)

    return getter


def test_list_models_parses_the_catalogue(monkeypatch):
    monkeypatch.setattr(llm, "require_key", lambda name: "test-key")
    monkeypatch.setattr(
        httpx,
        "get",
        fake_models_response(
            {
                "data": [
                    {
                        "id": "openai/gpt-4o",
                        "name": "GPT-4o",
                        "context_length": 128000,
                        "architecture": {"input_modalities": ["text", "image"]},
                        "pricing": {"prompt": "0.0000025", "completion": "0.00001"},
                    },
                    {
                        "id": "meta-llama/llama-3.3-70b-instruct:free",
                        "name": "Llama 3.3 70B (free)",
                        "context_length": 65536,
                        "architecture": {"input_modalities": ["text"]},
                        "pricing": {"prompt": "0", "completion": "0"},
                    },
                ]
            }
        ),
    )

    models = llm.list_models()

    assert len(models) == 2
    vision = next(m for m in models if m.id == "openai/gpt-4o")
    assert vision.supports_images is True
    assert vision.context_length == 128000

    free = next(m for m in models if m.id.endswith(":free"))
    assert free.supports_images is False
    assert free.is_free is True


def test_list_models_reads_the_legacy_modality_field(monkeypatch):
    """OpenRouter renamed this; both spellings must mark vision correctly."""
    monkeypatch.setattr(llm, "require_key", lambda name: "test-key")
    monkeypatch.setattr(
        httpx,
        "get",
        fake_models_response(
            {"data": [{"id": "a/b", "architecture": {"modality": "text+image->text"}}]}
        ),
    )
    assert llm.list_models()[0].supports_images is True


def test_list_models_skips_malformed_entries(monkeypatch):
    """One bad row must not hide the whole catalogue."""
    monkeypatch.setattr(llm, "require_key", lambda name: "test-key")
    monkeypatch.setattr(
        httpx,
        "get",
        fake_models_response({"data": [{"no_id": True}, {"id": "good/model"}]}),
    )

    models = llm.list_models()
    assert [m.id for m in models] == ["good/model"]


def test_list_models_tolerates_missing_pricing(monkeypatch):
    monkeypatch.setattr(llm, "require_key", lambda name: "test-key")
    monkeypatch.setattr(
        httpx,
        "get",
        fake_models_response({"data": [{"id": "a/b", "pricing": {"prompt": "not-a-number"}}]}),
    )
    assert llm.list_models()[0].prompt_price == 0.0


def test_list_models_surfaces_a_bad_key(monkeypatch):
    monkeypatch.setattr(llm, "require_key", lambda name: "bad-key")
    monkeypatch.setattr(httpx, "get", fake_models_response({}, status_code=401))

    with pytest.raises(llm.LLMError, match="API key"):
        llm.list_models()


def test_list_models_surfaces_a_network_failure(monkeypatch):
    monkeypatch.setattr(llm, "require_key", lambda name: "test-key")

    def failing(*args, **kwargs):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(httpx, "get", failing)

    with pytest.raises(llm.LLMError, match="Could not reach OpenRouter"):
        llm.list_models()
