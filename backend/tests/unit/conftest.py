"""Unit tests package — shared fixtures live in tests/conftest.py."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _stub_tinvest_enrichment_in_unit_tests() -> Generator[None, None, None]:
    """Stub T-Invest enrichment: mark bonds API-tradable without network I/O."""

    def _enrich(bonds: list[Any], _token: str) -> list[Any]:
        for bond in bonds:
            if bond.api_trade_available_flag is None:
                bond.api_trade_available_flag = True
            if not bond.figi and bond.isin:
                bond.figi = f"FIGI_{bond.isin[-8:]}"
            bond.tinvest_enriched = True
        return bonds

    with patch(
        "bond_monitor.application.bonds.bond_service.enrich_bonds_from_tinvest",
        side_effect=_enrich,
    ):
        yield
