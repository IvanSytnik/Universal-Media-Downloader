"""Smoke test: dispatcher wires up without a real bot token or network."""

from __future__ import annotations

from src.presentation.telegram.bot import create_dispatcher


def test_dispatcher_includes_basic_router() -> None:
    dp = create_dispatcher()

    router_names = {router.name for router in dp.sub_routers}
    assert "basic" in router_names
