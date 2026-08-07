"""Image understanding via the Claude API.

This is the one place in ingestion where data leaves the machine: the image
bytes are sent to Anthropic so Claude can describe them. The description is what
gets embedded and stored — embedding still happens locally.
"""

from __future__ import annotations

import base64
import logging

import anthropic

from app.config import get_settings, require_key

logger = logging.getLogger("merror.vision")

# Formats the Claude API accepts.
SUPPORTED_IMAGE_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

# The API rejects images over 5 MB once base64-encoded. Encoding inflates by
# ~4/3, so the raw-byte ceiling is lower than the documented limit.
MAX_IMAGE_BYTES = 3_750_000

# Enough for a rich description plus adaptive thinking, well under any timeout.
MAX_DESCRIPTION_TOKENS = 4096

EXTRACTION_PROMPT = """\
Describe this image for someone who cannot see it, as an entry in their personal \
memory archive. They will later search this archive by meaning, so the \
description is the only thing that can surface this image again.

Cover, in flowing prose rather than a list:
- What the image shows: setting, people, objects, actions, mood.
- Any text visible in the image, transcribed exactly.
- Details that suggest when, where, or why it was taken.

Be specific and concrete. Do not preface the description or comment on the \
image's quality — write only the description itself."""


class VisionError(RuntimeError):
    """Claude could not describe the image."""


class ImageRefusedError(VisionError):
    """Claude's safety classifiers declined to describe the image."""


def media_type_for(extension: str) -> str | None:
    """Map a file extension to the media type the API expects."""
    return SUPPORTED_IMAGE_TYPES.get(extension.lower())


def _client() -> anthropic.Anthropic:
    """Build an API client, failing loudly if the key is unset."""
    return anthropic.Anthropic(api_key=require_key("ANTHROPIC_API_KEY"))


def describe_image(data: bytes, media_type: str, *, filename: str = "") -> str:
    """Send an image to Claude and return a description of it.

    Raises ImageRefusedError if the model declines, and VisionError for
    transport or API failures.
    """
    if not data:
        raise VisionError("The image file is empty.")
    if len(data) > MAX_IMAGE_BYTES:
        raise VisionError(
            f"Image is {len(data) / 1_048_576:.1f} MB, over the "
            f"{MAX_IMAGE_BYTES / 1_048_576:.1f} MB limit. Resize it and retry."
        )

    settings = get_settings()
    encoded = base64.standard_b64encode(data).decode("ascii")

    try:
        response = _client().messages.create(
            model=settings.anthropic_model,
            max_tokens=MAX_DESCRIPTION_TOKENS,
            # Describing an image is perception, not deep reasoning; low effort
            # keeps latency and cost down without hurting the description.
            output_config={"effort": "low"},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": encoded,
                            },
                        },
                        {"type": "text", "text": EXTRACTION_PROMPT},
                    ],
                }
            ],
        )
    except anthropic.AuthenticationError as exc:
        raise VisionError("Anthropic rejected the API key. Check ANTHROPIC_API_KEY.") from exc
    except anthropic.RateLimitError as exc:
        raise VisionError("Anthropic rate limit reached. Wait a moment and retry.") from exc
    except anthropic.APIStatusError as exc:
        raise VisionError(f"Anthropic returned {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise VisionError("Could not reach Anthropic. Check your connection.") from exc

    # Check stop_reason before touching content: on a refusal the response is a
    # normal 200 whose content list is empty or partial.
    if response.stop_reason == "refusal":
        category = getattr(response.stop_details, "category", None)
        logger.warning("Image description refused (%s) for %s", category, filename or "image")
        raise ImageRefusedError(
            "Claude declined to describe this image"
            + (f" ({category})" if category else "")
            + ". It has not been stored."
        )

    description = "\n\n".join(
        block.text.strip() for block in response.content if block.type == "text" and block.text.strip()
    )

    if not description:
        raise VisionError("Claude returned no description for this image.")

    if response.stop_reason == "max_tokens":
        logger.warning("Description for %s was truncated at the token limit", filename or "image")

    logger.info("Described %s (%d chars)", filename or "image", len(description))
    return description
