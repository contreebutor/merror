"""Splitting long text into embeddable chunks.

Strategy: paragraph-aware with a size cap.

Paragraphs are the unit of meaning in the material MERROR is built for —
journals, notes, essays — so boundaries follow them wherever possible:

1. Split on blank lines into paragraphs.
2. Pack consecutive paragraphs together while they fit under MAX_CHUNK_CHARS,
   so a run of one-line notes becomes one coherent chunk instead of a dozen
   context-free fragments.
3. Split any paragraph that alone exceeds the cap at sentence boundaries, never
   mid-sentence.
4. Carry OVERLAP_CHARS of trailing context into the next chunk, so a fact
   stated across a boundary is still retrievable from both sides.

Sizes are in characters rather than tokens deliberately: the embedding model
(all-MiniLM-L6-v2) truncates at 256 word-pieces, roughly 1000-1200 characters of
English prose, and a character budget avoids a tokenizer dependency for a
approximation that only needs to be close.
"""

from __future__ import annotations

import re

# Sized to stay under the embedding model's 256 word-piece window. Going over
# does not error — the tail is silently ignored, which is worse than a warning.
MAX_CHUNK_CHARS = 1200

# Trailing context repeated into the following chunk.
OVERLAP_CHARS = 150

# Chunks shorter than this are merged into a neighbour; alone they carry too
# little signal to embed usefully.
MIN_CHUNK_CHARS = 80

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n+")

# Split after ., !, or ? plus any closing quote/bracket, followed by whitespace.
# Python's re requires fixed-width lookbehind, so abbreviations cannot be
# excluded here — false splits are merged back in `split_sentences`.
_SENTENCE_END = re.compile(r"(?<=[.!?])[\"')\]]*\s+")

# Abbreviations whose trailing period does not end a sentence.
_ABBREVIATIONS = frozenset(
    """mr mrs ms dr prof st jr sr vs etc eg ie approx dept est fig
    no vol pp ca cf al inc ltd co jan feb mar apr jun jul aug sep sept oct nov dec""".split()
)

# A fragment ending in an initial ("J.") or a known abbreviation ("Dr.").
_FALSE_ENDING = re.compile(r"(?:\b[A-Za-z]|\b([A-Za-z]+))\.[\"')\]]*$")


def normalise_whitespace(text: str) -> str:
    """Collapse runs of spaces and blank lines without losing paragraph breaks."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _ends_mid_sentence(fragment: str) -> bool:
    """True if a fragment's final period is an abbreviation or initial.

    "Dr." and "J." look like sentence ends to the regex but are not, so the
    following fragment gets merged back rather than split off.
    """
    match = _FALSE_ENDING.search(fragment)
    if match is None:
        return False
    word = match.group(1)
    # No captured group means a single-letter initial, e.g. "J.".
    return word is None or word.lower() in _ABBREVIATIONS


def split_sentences(text: str) -> list[str]:
    """Split a paragraph into sentences, keeping terminal punctuation."""
    parts = [s.strip() for s in _SENTENCE_END.split(text) if s and s.strip()]
    if not parts:
        return [text.strip()] if text.strip() else []

    merged = [parts[0]]
    for part in parts[1:]:
        if _ends_mid_sentence(merged[-1]):
            merged[-1] = f"{merged[-1]} {part}"
        else:
            merged.append(part)
    return merged


def _split_long_paragraph(paragraph: str) -> list[str]:
    """Break an over-cap paragraph at sentence boundaries."""
    chunks: list[str] = []
    current = ""

    for sentence in split_sentences(paragraph):
        # A single sentence longer than the cap has no clean split point, so
        # fall back to hard-wrapping it on the character budget.
        if len(sentence) > MAX_CHUNK_CHARS:
            if current:
                chunks.append(current)
                current = ""
            for i in range(0, len(sentence), MAX_CHUNK_CHARS):
                chunks.append(sentence[i : i + MAX_CHUNK_CHARS].strip())
            continue

        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= MAX_CHUNK_CHARS:
            current = candidate
        else:
            chunks.append(current)
            current = sentence

    if current:
        chunks.append(current)
    return chunks


def _tail_overlap(text: str) -> str:
    """Last OVERLAP_CHARS of `text`, trimmed to a word boundary."""
    if len(text) <= OVERLAP_CHARS:
        return text
    tail = text[-OVERLAP_CHARS:]
    space = tail.find(" ")
    return tail[space + 1 :] if space != -1 else tail


def chunk_text(text: str, *, overlap: bool = True) -> list[str]:
    """Split `text` into embeddable chunks. Returns [] for empty input."""
    text = normalise_whitespace(text)
    if not text:
        return []

    # Stage 1: paragraphs, with over-cap ones pre-split at sentence boundaries.
    units: list[str] = []
    for paragraph in _PARAGRAPH_BREAK.split(text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) > MAX_CHUNK_CHARS:
            units.extend(_split_long_paragraph(paragraph))
        else:
            units.append(paragraph)

    # Stage 2: pack consecutive units up to the cap.
    packed: list[str] = []
    current = ""
    for unit in units:
        candidate = f"{current}\n\n{unit}" if current else unit
        if len(candidate) <= MAX_CHUNK_CHARS:
            current = candidate
        else:
            if current:
                packed.append(current)
            current = unit
    if current:
        packed.append(current)

    # Stage 3: absorb a runt trailing chunk into its predecessor when there is
    # room, so a document never ends on a fragment.
    if len(packed) > 1 and len(packed[-1]) < MIN_CHUNK_CHARS:
        merged = f"{packed[-2]}\n\n{packed[-1]}"
        if len(merged) <= MAX_CHUNK_CHARS:
            packed = packed[:-2] + [merged]

    if not overlap or len(packed) == 1:
        return packed

    # Stage 4: prepend trailing context from the previous chunk.
    result = [packed[0]]
    for previous, chunk in zip(packed, packed[1:]):
        result.append(f"{_tail_overlap(previous)} {chunk}".strip())
    return result
