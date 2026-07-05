"""FSM states for the guided download flow.

Stored in RedisStorage (see main.py), NOT in-memory MemoryStorage —
state must survive bot restarts and, later, multiple bot instances
(Phase 7 horizontal scaling). Redis is already in the stack, so this
costs zero new infrastructure.
"""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class DownloadFlow(StatesGroup):
    # Set after the user taps "⬇️ Скачать": the next message they send
    # is treated as the URL to preview. Cleared as soon as a URL (valid
    # or not) arrives, so the user is never trapped in the state.
    waiting_for_url = State()
