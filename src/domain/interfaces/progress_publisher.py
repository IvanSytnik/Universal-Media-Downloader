"""ProgressPublisherPort — domain interface for broadcasting download
progress. Day 11B.

``chat_id``/``message_id``/``language`` are passed as plain primitives
alongside ``progress``, exactly the way ``NotifierPort.send_file`` already
takes a bare ``telegram_id: int`` and ``ErrorLocalizerPort.localize``
already takes a bare ``locale: str | None`` — the domain doesn't know
these numbers mean "a Telegram chat" or "an FTL locale code", only that
they're routing/rendering parameters an implementation needs. This is
the established pattern in this codebase, not a new exception to the
Dependency Rule (docs/architecture.md, Progress bridge).

The implementation (RedisProgressPublisher) folds all of this into one
JSON event so the Presentation-layer listener never needs a DB round
trip per progress update.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from src.domain.value_objects.download_progress import DownloadProgress


class ProgressPublisherPort(Protocol):
    async def publish(
        self,
        request_id: UUID,
        chat_id: int,
        message_id: int,
        language: str | None,
        progress: DownloadProgress,
    ) -> None:
        """Broadcast one progress snapshot for ``request_id``.

        ``chat_id``/``message_id`` identify which message to render
        progress into; ``language`` is the user's stored locale (or None
        for the implementation's default) so the listener can localize
        without a DB read on the hot path."""
        ...
