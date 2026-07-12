"""Smoke test: dispatcher wires up without a real bot token or network.

Day 9: create_dispatcher requires the i18n middleware and the button
translation sets (built from a started core). We build both from the
real core with no Redis (override path simply stays inactive), and an
in-memory FSM storage — enough to assert the routers are wired.
"""

from __future__ import annotations

import pytest
from aiogram.fsm.storage.memory import MemoryStorage

from src.presentation.telegram.bot import (
    collect_button_translations,
    create_dispatcher,
)
from src.presentation.telegram.i18n import create_i18n_core, create_i18n_middleware


@pytest.mark.asyncio
async def test_dispatcher_includes_basic_router() -> None:
    core = create_i18n_core()
    await core.startup()

    dp = create_dispatcher(
        i18n_middleware=create_i18n_middleware(core, redis=None),
        button_translations=collect_button_translations(core),
        storage=MemoryStorage(),
    )

    router_names = {router.name for router in dp.sub_routers}
    assert "basic" in router_names
