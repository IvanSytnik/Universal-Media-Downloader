"""delivery_filename tests — the delivered file is named by the title,
sanitized; no usable title falls back to the on-disk ``<id>.<ext>``."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.domain.value_objects.deliverable_media import DeliverableMedia
from src.domain.value_objects.delivery_filename import MAX_FILENAME_BYTES, delivery_filename
from src.domain.value_objects.download_result import DownloadResult
from src.domain.value_objects.format_kind import FormatKind

VIDEO = Path("/tmp/umd-downloads/req/dQw4w9WgXcQ.mp4")
AUDIO = Path("/tmp/umd-downloads/req/dQw4w9WgXcQ.mp3")


def test_title_names_the_file_with_the_real_extension() -> None:
    assert delivery_filename("Never Gonna Give You Up", VIDEO) == "Never Gonna Give You Up.mp4"
    assert delivery_filename("Never Gonna Give You Up", AUDIO) == "Never Gonna Give You Up.mp3"


def test_cyrillic_and_emoji_are_kept() -> None:
    assert delivery_filename("Кино — Группа крови 🎸", VIDEO) == "Кино — Группа крови 🎸.mp4"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ('AC/DC: "Back in Black"', "AC DC Back in Black.mp4"),
        ("a\\b*c?d<e>f|g", "a b c d e f g.mp4"),
        ("../../etc/passwd", "etc passwd.mp4"),
    ],
)
def test_forbidden_characters_are_replaced(title: str, expected: str) -> None:
    assert delivery_filename(title, VIDEO) == expected


def test_whitespace_is_normalized_and_collapsed() -> None:
    assert delivery_filename("  Live\tat\n\nWembley\u00a0 1986  ", VIDEO) == (
        "Live at Wembley 1986.mp4"
    )


def test_control_and_invisible_format_characters_are_dropped() -> None:
    # U+202E would render "evil\u202egpj.exe" as "evilexe.jpg".
    title = "evil\u202egpj\x00\x1b\u200b.exe clip"
    assert delivery_filename(title, VIDEO) == "evilgpj.exe clip.mp4"


def test_leading_and_trailing_dots_are_trimmed() -> None:
    # A leading dot hides the file; Windows strips a trailing one.
    assert delivery_filename(".hidden...", VIDEO) == "hidden.mp4"


def test_decomposed_unicode_is_normalized_to_nfc() -> None:
    decomposed = "\u0418\u0306"  # И + combining breve
    assert delivery_filename(decomposed, VIDEO) == "\u0419.mp4"


@pytest.mark.parametrize("title", [None, "", "   ", "///", "..", "\u200b\u202e", '<>:"|?*'])
def test_no_usable_title_falls_back_to_the_id_name(title: str | None) -> None:
    assert delivery_filename(title, VIDEO) == "dQw4w9WgXcQ.mp4"


@pytest.mark.parametrize("char", ["a", "я", "🎸"])
def test_long_title_is_cut_to_the_byte_budget_on_a_character_boundary(char: str) -> None:
    name = delivery_filename(char * 500, VIDEO)

    assert len(name.encode("utf-8")) <= MAX_FILENAME_BYTES
    assert name.endswith(".mp4")
    stem = name.removesuffix(".mp4")
    # Whole characters only, and as many as fit.
    assert set(stem) == {char}
    assert len((stem + char + ".mp4").encode("utf-8")) > MAX_FILENAME_BYTES


def test_cut_never_leaves_a_trailing_space_or_dot() -> None:
    budget = MAX_FILENAME_BYTES - len(".mp4")
    title = "a" * (budget - 1) + " ." + "b" * 50
    assert delivery_filename(title, VIDEO) == "a" * (budget - 1) + ".mp4"


def test_file_without_extension_keeps_none() -> None:
    assert delivery_filename("clip", Path("/tmp/x/abc")) == "clip"
    assert delivery_filename(None, Path("/tmp/x/abc")) == "abc"


@pytest.mark.parametrize("kind", [FormatKind.VIDEO, FormatKind.AUDIO])
def test_deliverable_media_carries_the_title_filename(kind: FormatKind) -> None:
    path = VIDEO if kind is FormatKind.VIDEO else AUDIO
    media = DeliverableMedia.from_result(DownloadResult(path=path, title="Song: Live"), kind)

    assert media.filename == f"Song Live{path.suffix}"


def test_deliverable_media_without_title_uses_the_id_name() -> None:
    media = DeliverableMedia.from_result(DownloadResult(path=VIDEO), FormatKind.VIDEO)

    assert media.filename == "dQw4w9WgXcQ.mp4"
