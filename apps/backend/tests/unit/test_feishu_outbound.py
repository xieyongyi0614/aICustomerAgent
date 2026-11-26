import pytest

from app.channels.feishu.outbound import MAX_PARTS, normalize_text, split_text


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("a\r\nb", "a\nb"),
        ("a\rb", "a\nb"),
        ("\n  hi  \n", "hi"),
        ("  x  ", "x"),
        ("   ", ""),
        ("", ""),
    ],
)
def test_normalize_basic(raw, expected):
    assert normalize_text(raw) == expected


def test_normalize_removes_control_chars_keeps_newline_tab():
    assert normalize_text("a\x00b\x07c") == "abc"
    assert normalize_text("a\nb\tc") == "a\nb\tc"


def test_normalize_idempotent():
    sample = "  好\r\n\nbad\x07\n\t text  "
    assert normalize_text(normalize_text(sample)) == normalize_text(sample)


def test_normalize_preserves_markdown_and_indent():
    sample = "  **bold**\n    indented code  "
    normalized = normalize_text(sample)
    assert "**bold**" in normalized
    assert "    indented code" in normalized


def _invariants(text, max_chars):
    parts = split_text(text, max_chars)
    assert "".join(parts) == text
    assert all(len(part) <= max_chars for part in parts)
    assert parts
    return parts


@pytest.mark.parametrize(
    "text",
    [
        "short",
        "啊" * 900,
        "line1\nline2\n\npara2\nline3",
        "一。二！三？四；五…六.",
        "space separated words " * 9,
        "😀😃😄🀀🈁" * 40,
        "中文" * 600,
        "a" * 7 + "👍" * 200,
    ],
)
def test_split_invariants_over_samples(text):
    for max_chars in (max(len(text) // 3, 1), max(len(text) // 2, 1), max(len(text), 1)):
        _invariants(text, max_chars)


def test_split_paragraph_break_preferred():
    text = "a" * 8 + "\n\n" + "b" * 8
    parts = split_text(text, 10)
    assert parts == ["a" * 8 + "\n\n", "b" * 8]


def test_split_line_break_next():
    text = "aaaa\nbbbb"
    parts = split_text(text, 5)
    assert parts == ["aaaa\n", "bbbb"]


def test_split_sentence_punct_next():
    text = "你好。世界！加油？"
    parts = split_text(text, 4)
    assert "".join(parts) == text
    assert parts[0].endswith("。")


def test_split_soft_break_last():
    text = "word word word"
    parts = split_text(text, 5)
    assert "".join(parts) == text
    assert parts[0].rstrip() == "word"


def test_split_hard_cut_without_boundaries():
    text = "啊" * 900
    parts = split_text(text, 100)
    assert len(parts) == 9
    assert "".join(parts) == text


def test_split_max_parts_truncates_last():
    text = "。" * (MAX_PARTS * 30)
    parts = split_text(text, 10)
    assert len(parts) == MAX_PARTS
    assert all(len(part) <= 10 for part in parts)
    assert len("".join(parts)) < len(text)


def test_split_empty_input():
    assert split_text("", 10) == []


def test_split_max_chars_one_does_not_crash():
    parts = split_text("ab👍c", 1)
    assert "".join(parts) == "ab👍c"
    assert all(len(part) == 1 for part in parts)


def test_split_astral_emoji_not_corrupted():
    text = "👍" * 20
    parts = split_text(text, 7)
    for part in parts:
        for char in part:
            assert char == "👍"
    assert "".join(parts) == text
