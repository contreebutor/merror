"""Tests for image description and local image storage."""

import base64

import anthropic
import httpx
import pytest

from app import media, vision
from tests.helpers import (
    make_gif,
    make_jpeg,
    make_png,
    make_webp,
    refusal_response,
    text_response,
)


def api_error(status_code: int, message: str = "boom") -> anthropic.APIStatusError:
    """Build the exception the SDK actually raises for a given status.

    The SDK raises status-specific subclasses, not a bare APIStatusError, so
    the test must too — otherwise the handlers for those subclasses are never
    exercised and the test passes for the wrong reason.
    """
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status_code, request=request, json={"error": {"message": message}})
    error_class = {
        401: anthropic.AuthenticationError,
        429: anthropic.RateLimitError,
    }.get(status_code, anthropic.APIStatusError)
    return error_class(message, response=response, body=None)


# --- Media type detection --------------------------------------------------


def test_extension_to_media_type():
    assert vision.media_type_for(".JPG") == "image/jpeg"
    assert vision.media_type_for(".png") == "image/png"
    assert vision.media_type_for(".pdf") is None


def test_sniff_detects_every_supported_format():
    assert media.sniff_media_type(make_png()) == "image/png"
    assert media.sniff_media_type(make_jpeg()) == "image/jpeg"
    assert media.sniff_media_type(make_gif()) == "image/gif"
    assert media.sniff_media_type(make_webp()) == "image/webp"


def test_sniff_rejects_non_images():
    assert media.sniff_media_type(b"%PDF-1.4 not an image") is None
    assert media.sniff_media_type(b"") is None
    # A RIFF container that is not WebP (e.g. a WAV file).
    assert media.sniff_media_type(b"RIFF\x00\x00\x00\x00WAVE") is None


# --- Describing images -----------------------------------------------------


def test_describe_image_returns_text(fake_vision):
    client = fake_vision(text_response("A quiet kitchen at dawn."))

    result = vision.describe_image(make_png(), "image/png", filename="kitchen.png")

    assert result == "A quiet kitchen at dawn."
    assert len(client.messages.calls) == 1


def test_describe_image_sends_correct_payload(fake_vision):
    data = make_png()
    client = fake_vision(text_response("description"))

    vision.describe_image(data, "image/png")

    call = client.messages.calls[0]
    assert call["model"] == "claude-opus-5"
    assert call["output_config"] == {"effort": "low"}

    image_block, text_block = call["messages"][0]["content"]
    assert image_block["source"]["media_type"] == "image/png"
    # The image must be transmitted intact, not truncated or re-encoded.
    assert base64.standard_b64decode(image_block["source"]["data"]) == data
    assert "cannot see it" in text_block["text"]


def test_refusal_raises_before_reading_content(fake_vision):
    # A refusal is a 200 with empty content — reading content[0] would IndexError.
    fake_vision(refusal_response(category="privacy"))

    with pytest.raises(vision.ImageRefusedError) as exc:
        vision.describe_image(make_png(), "image/png")

    assert "privacy" in str(exc.value)
    assert "not been stored" in str(exc.value)


def test_empty_description_raises(fake_vision):
    from tests.helpers import FakeMessage

    # A successful response that happens to carry no text.
    fake_vision(FakeMessage())

    with pytest.raises(vision.VisionError, match="no description"):
        vision.describe_image(make_png(), "image/png")


def test_empty_image_rejected_without_calling_api(fake_vision):
    client = fake_vision(text_response("unused"))

    with pytest.raises(vision.VisionError):
        vision.describe_image(b"", "image/png")

    assert client.messages.calls == [], "should not spend an API call on an empty file"


def test_oversized_image_rejected_without_calling_api(fake_vision):
    client = fake_vision(text_response("unused"))

    with pytest.raises(vision.VisionError, match="over the"):
        vision.describe_image(b"\x89PNG" + b"x" * vision.MAX_IMAGE_BYTES, "image/png")

    assert client.messages.calls == []


@pytest.mark.parametrize(
    "error,expected",
    [
        (api_error(401), "API key"),
        (api_error(429), "rate limit"),
        (api_error(500), "500"),
    ],
)
def test_api_errors_become_readable_messages(fake_vision, error, expected):
    fake_vision(error)

    with pytest.raises(vision.VisionError) as exc:
        vision.describe_image(make_png(), "image/png")

    assert expected.lower() in str(exc.value).lower()


def test_connection_error_is_handled(fake_vision):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    fake_vision(anthropic.APIConnectionError(request=request))

    with pytest.raises(vision.VisionError, match="reach Anthropic"):
        vision.describe_image(make_png(), "image/png")


# --- Local storage ---------------------------------------------------------


def test_save_and_delete_image():
    path = media.save_image("abc123", ".png", make_png())

    assert path.exists()
    assert path.name == "abc123.png"
    assert media.delete_image(path) is True
    assert not path.exists()


def test_filename_comes_from_memory_id_not_upload():
    # A hostile upload name must not influence where the file lands.
    path = media.save_image("safe-id", ".PNG", make_png())
    assert path.name == "safe-id.png"
    assert path.parent == media.images_dir()


def test_save_rejects_suspicious_extension():
    with pytest.raises(ValueError):
        media.save_image("id", "./../evil", b"data")


def test_delete_refuses_paths_outside_images_dir(tmp_path):
    outsider = tmp_path / "important.txt"
    outsider.write_text("do not delete me")

    assert media.delete_image(outsider) is False
    assert outsider.exists(), "deletion must not escape the images directory"


def test_delete_missing_file_returns_false():
    assert media.delete_image(media.images_dir() / "nope.png") is False
    assert media.delete_image("") is False
