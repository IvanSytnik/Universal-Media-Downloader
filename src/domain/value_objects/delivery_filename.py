"""delivery_filename — the name a delivered file carries to the user
(Backlog: file names by title instead of video id).

The file on disk keeps yt-dlp's ``<id>.<ext>`` name: post_hooks report it
(bug #4), ``restrictfilenames`` keeps it ASCII, and two requests for
different videos with the same title can't collide in the download dir.
Only the name the recipient sees comes from the title, so it is built
here, from untrusted extractor text, and never touches the filesystem
of the worker.

The title is sanitized for the filesystems the recipient may save to:
path separators and characters Windows forbids are replaced, control
and invisible format characters (incl. RTL overrides that can disguise
an extension) are dropped, whitespace is collapsed, leading/trailing
dots and spaces are trimmed, and the result is cut to a byte budget well
under ext4's 255-byte limit — counted in UTF-8, so a Cyrillic title
gets half the characters of a Latin one and is never cut mid-character.
Nothing usable left → the on-disk ``<id>.<ext>`` name, as before.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

# Bytes, extension included. ext4 allows 255; the margin leaves room for
# a " (1)" a client appends on a duplicate download.
MAX_FILENAME_BYTES = 180

_FORBIDDEN = frozenset('/\\:*?"<>|')
# Cc: control characters (NUL, newline, ESC...). Cf: invisible format
# characters (zero-width spaces, bidi overrides like U+202E).
_DROPPED_CATEGORIES = frozenset({"Cc", "Cf"})
_TRIMMED = " ."


def delivery_filename(title: str | None, path: Path) -> str:
    """The title as a safe file name with ``path``'s extension, or
    ``path.name`` when the title yields nothing usable."""
    suffix = path.suffix
    stem = _sanitize(title or "")
    budget = MAX_FILENAME_BYTES - len(suffix.encode("utf-8"))
    stem = _truncate_utf8(stem, budget).strip(_TRIMMED)
    if not stem:
        return path.name
    return f"{stem}{suffix}"


def _sanitize(title: str) -> str:
    # NFC first: a decomposed "й" is two code points and more bytes.
    text = unicodedata.normalize("NFC", title)
    chars = (
        " " if ch in _FORBIDDEN else ch
        for ch in text
        if unicodedata.category(ch) not in _DROPPED_CATEGORIES or ch in "\t\n\r"
    )
    # str.split() without arguments splits on any Unicode whitespace —
    # tabs, newlines, NBSP — so this both normalizes and collapses it.
    return " ".join("".join(chars).split()).strip(_TRIMMED)


def _truncate_utf8(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    # "ignore" drops a multi-byte character the cut split in half.
    return encoded[: max(max_bytes, 0)].decode("utf-8", errors="ignore")
