"""Tests for app/main.py's lifespan — specifically S9's non-blocking cache
warm: _warm_cache() used to run synchronously inside lifespan, blocking
Cloud Run's very first request after a cold start on a Firestore query.
This proves the fix actually is non-blocking, not just that the code looks
like it should be.
"""

import asyncio
import time
from unittest.mock import patch

import pytest

from app import main


class _FakeSessionManagerCtx:
    """Stands in for `async with mcp_server.session_manager.run():` — real
    session_manager.run() starts the streamable-HTTP transport's own task
    group, which this test has no reason to exercise; only lifespan's own
    background-task behavior around _warm_cache() is under test here."""

    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


@pytest.mark.asyncio
async def test_lifespan_does_not_block_readiness_on_cache_warm():
    warm_cache_finished = False

    def slow_warm_cache():
        # A stand-in for _warm_cache()'s real Firestore query — blocking,
        # since the Firestore client is sync, which is exactly why S9
        # wraps it in asyncio.to_thread rather than just awaiting it.
        nonlocal warm_cache_finished
        time.sleep(0.2)
        warm_cache_finished = True

    with (
        patch.object(main.mcp_server.session_manager, "run", lambda: _FakeSessionManagerCtx()),
        patch.object(main, "_warm_cache", slow_warm_cache),
    ):
        async with main.lifespan(main.app):
            # lifespan's own readiness point (the `yield`) must be reached
            # without waiting for _warm_cache's 0.2s of blocking work — that
            # is the entire point of firing it as a background task instead
            # of calling it inline.
            assert warm_cache_finished is False
            await asyncio.sleep(0.35)  # let the background task actually finish
            assert warm_cache_finished is True


@pytest.mark.asyncio
async def test_a_warm_cache_failure_does_not_propagate_out_of_lifespan():
    """_warm_cache() already catches its own exceptions and logs a warning
    (see its own try/except) — this confirms that guarantee survives being
    moved onto a background task: a broken warm-cache call must not crash
    startup or block shutdown."""

    def raising_warm_cache():
        raise RuntimeError("Firestore is down")

    with (
        patch.object(main.mcp_server.session_manager, "run", lambda: _FakeSessionManagerCtx()),
        patch.object(main, "_warm_cache", raising_warm_cache),
    ):
        async with main.lifespan(main.app):
            await asyncio.sleep(0.05)
        # Reaching here (no exception propagated past the `async with`)
        # is the assertion.
