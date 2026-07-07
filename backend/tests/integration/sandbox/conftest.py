"""Sandbox integration test fixtures."""

from __future__ import annotations

import os

import pytest

_SANDBOX_TOKEN: str = os.getenv("T_TRADING_TOKEN_SANDBOX", "").strip()
_SKIP_REASON = "T_TRADING_TOKEN_SANDBOX не задан — e2e в sandbox пропускается"


@pytest.fixture(scope="session")
def sandbox_token() -> str:
    if not _SANDBOX_TOKEN:
        pytest.skip(_SKIP_REASON)
    return _SANDBOX_TOKEN
