"""PreviewContextStorePort — short-lived storage that maps an opaque
token to a PreviewContext (Day 7: a bare source URL; Day 11C v2: the URL
plus the extractor key and compatible short side the buttons need).

Why this exists at all: Telegram limits `callback_data` on inline
buttons to 64 bytes — a real URL simply does not fit. So the ✅ button
under a preview carries only a short token; the URL itself lives here,
keyed by that token, with a TTL. Token expiry doubles as UX protection
against clicking a week-old preview button.

Domain knows nothing about Redis — the interface speaks in tokens and
PreviewContext only. The Redis implementation lives in infrastructure.
"""

from __future__ import annotations

from typing import Protocol

from src.domain.value_objects.preview_context import PreviewContext


class PreviewContextStorePort(Protocol):
    async def save(self, context: PreviewContext) -> str:
        """Stores `context` and returns an opaque token (short, callback-safe).

        The stored entry expires after an implementation-configured TTL.
        """
        ...

    async def get(self, token: str) -> PreviewContext | None:
        """Returns the context for `token`, or None if unknown/expired
        (or unreadable — treated exactly like expired)."""
        ...

    async def delete(self, token: str) -> None:
        """Removes the entry, if present. Idempotent — deleting a
        missing/expired token is not an error (the user may double-tap
        the button, or cancel after expiry)."""
        ...

    async def pop(self, token: str) -> PreviewContext | None:
        """Atomically returns the context for `token` AND removes it.

        Day 11C stage 4. ``get`` followed by ``delete`` is not equivalent:
        two fast taps on the same button both complete their ``get``
        before either ``delete`` lands, and the download is enqueued
        twice. Claiming the token in one round trip makes the second tap
        see None and fall through to the stale-preview path, so
        "first tap wins" is enforced by the store rather than by luck.

        Use this wherever consuming the token commits to an action; keep
        ``get`` for read-only steps (e.g. opening the quality picker,
        which the user may still back out of).
        """
        ...
