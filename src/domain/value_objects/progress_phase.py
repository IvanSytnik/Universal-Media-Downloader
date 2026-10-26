"""ProgressPhase — which phase of a download a DownloadProgress snapshot
describes (Day 11B.1).

Same precedent as ``FormatKind``: a small domain enum instead of a bare
string, so an unrecognized/missing value has one safe default
(``DOWNLOADING``) instead of three different magic strings scattered
across the VO, the downloader, and the presentation listener.

``StrEnum`` matters here specifically: it lets a ``ProgressPhase`` member
cross the JSON boundary (``RedisProgressPublisher`` → ``json.dumps`` via
``dataclasses.asdict``) as a plain string automatically, with no manual
``.value`` conversion at the publish site — and it lets the listener
compare a plain string decoded from JSON directly against
``ProgressPhase.CONVERTING`` without ever constructing an enum member
from untrusted pubsub data (which would raise on an unknown value from a
newer producer during a rolling deploy).

Day 11D-2: three one-shot phases after the download itself —
``UPLOADING`` (the file is being sent to Telegram), then exactly one of
``DONE`` / ``FAILED``. Like ``CONVERTING`` they carry no byte/percent
data. ``DONE`` and ``FAILED`` are terminal: no event for the request
follows them.
"""

from __future__ import annotations

from enum import StrEnum


class ProgressPhase(StrEnum):
    DOWNLOADING = "downloading"
    CONVERTING = "converting"
    UPLOADING = "uploading"
    DONE = "done"
    FAILED = "failed"
