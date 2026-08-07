"""Tests for paragraph-aware chunking."""

from app.chunking import (
    MAX_CHUNK_CHARS,
    OVERLAP_CHARS,
    chunk_text,
    normalise_whitespace,
    split_sentences,
)


def test_empty_input_yields_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   \n\n  \t ") == []


def test_short_text_is_one_chunk():
    assert chunk_text("A single short thought.") == ["A single short thought."]


def test_small_paragraphs_are_packed_together():
    text = "First short note.\n\nSecond short note.\n\nThird short note."
    chunks = chunk_text(text)

    assert len(chunks) == 1, "small paragraphs should not become separate chunks"
    assert "First" in chunks[0] and "Third" in chunks[0]


def test_paragraph_boundaries_are_preserved_when_packed():
    chunks = chunk_text("Alpha para.\n\nBeta para.")
    assert "\n\n" in chunks[0]


def test_every_chunk_respects_the_cap():
    text = "\n\n".join(f"Paragraph {i}. " + "filler words here. " * 30 for i in range(20))
    for chunk in chunk_text(text):
        assert len(chunk) <= MAX_CHUNK_CHARS + OVERLAP_CHARS + 1


def test_long_paragraph_splits_at_sentence_boundaries():
    sentence = "This is a complete sentence about something memorable. "
    chunks = chunk_text(sentence * 60, overlap=False)

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.rstrip().endswith("."), f"chunk cut mid-sentence: ...{chunk[-40:]!r}"


def test_overlap_carries_context_forward():
    text = "\n\n".join("Sentence block number %d. " % i * 20 for i in range(6))
    with_overlap = chunk_text(text, overlap=True)
    without = chunk_text(text, overlap=False)

    assert len(with_overlap) == len(without)
    # Each later chunk should start with a tail borrowed from its predecessor.
    for i in range(1, len(with_overlap)):
        assert len(with_overlap[i]) > len(without[i])


def test_no_overlap_when_only_one_chunk():
    assert chunk_text("Just one small note.") == ["Just one small note."]


def test_single_giant_sentence_is_hard_wrapped():
    # No sentence boundary to split on; must still respect the cap.
    chunks = chunk_text("word " * 2000, overlap=False)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= MAX_CHUNK_CHARS


def test_chunks_are_never_empty_or_whitespace():
    text = "\n\n\n".join(["Real content here." * 40, "   ", "More content." * 40])
    for chunk in chunk_text(text):
        assert chunk.strip(), "produced an empty chunk"


def test_no_content_is_lost():
    text = "\n\n".join(f"Unique marker {i} in this paragraph." for i in range(30))
    joined = " ".join(chunk_text(text, overlap=False))
    for i in range(30):
        assert f"Unique marker {i}" in joined


def test_normalise_whitespace_keeps_paragraph_breaks():
    assert normalise_whitespace("a  b\n\n\n\nc") == "a b\n\nc"
    assert normalise_whitespace("line\r\nline") == "line\nline"


def test_split_sentences_basic():
    assert split_sentences("One. Two! Three?") == ["One.", "Two!", "Three?"]


def test_split_sentences_ignores_common_abbreviations():
    result = split_sentences("Dr. Smith arrived. He was late.")
    assert len(result) == 2, f"abbreviation split incorrectly: {result}"


def test_trailing_runt_chunk_is_absorbed():
    body = "Substantial paragraph content here. " * 30
    chunks = chunk_text(f"{body}\n\nTiny.", overlap=False)
    assert not chunks[-1].strip() == "Tiny.", "runt chunk should merge into predecessor"
