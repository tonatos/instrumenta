"""Deterministic identifiers for trading operations."""

from __future__ import annotations

import hashlib


def stable_id(portfolio_id: str, kind: str, key: str) -> str:
    """Детерминированный id для авто-генерируемых pending operations."""
    digest = hashlib.sha256(f"{portfolio_id}|{kind}|{key}".encode()).hexdigest()
    return digest[:32]
