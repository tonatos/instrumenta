"""Тесты снимка счёта: конвертация цен облигаций из ₽ в % номинала."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from bond_monitor.domain.portfolio.models import AccountKind
from bond_monitor.domain.shared.money import Rub
from bond_monitor.infrastructure.tinvest.trading_client import (
    _classify_position,
    get_account_snapshot,
)


def _quotation(value: float) -> SimpleNamespace:
    units = int(value)
    nano = int(round((value - units) * 1_000_000_000))
    return SimpleNamespace(units=units, nano=nano)


def _bond_portfolio_position(
    *,
    current_price_rub: float,
    average_price_rub: float,
    figi: str = "TCS00A10AU73",
) -> SimpleNamespace:
    return SimpleNamespace(
        instrument_type="bond",
        figi=figi,
        instrument_uid="uid-gtlk",
        ticker="RU000A10AU73",
        quantity=_quotation(66),
        quantity_lots=_quotation(66),
        blocked=_quotation(0),
        current_price=_quotation(current_price_rub),
        current_nkd=SimpleNamespace(units=2, nano=0, currency="rub"),
        average_position_price=SimpleNamespace(
            units=int(average_price_rub),
            nano=int(round((average_price_rub % 1) * 1_000_000_000)),
            currency="rub",
        ),
    )


def test_classify_bond_converts_portfolio_ruble_price_to_pct() -> None:
    """getPortfolio отдаёт current_price в ₽, а не в % от номинала."""
    kind, bond = _classify_position(
        _bond_portfolio_position(current_price_rub=1004.4, average_price_rub=1003.1),
        nominal_rub=1000.0,
    )

    assert kind == "bond"
    assert bond is not None
    assert float(bond.current_price_pct) == pytest.approx(100.44)
    assert float(bond.average_price_pct) == pytest.approx(100.31)


def test_classify_bond_without_nominal_leaves_price_pct_none() -> None:
    kind, bond = _classify_position(
        _bond_portfolio_position(current_price_rub=1004.4, average_price_rub=1003.1),
        nominal_rub=None,
    )

    assert kind == "bond"
    assert bond is not None
    assert bond.current_price_pct is None
    assert bond.average_price_pct is None


def test_get_account_snapshot_fetches_nominal_for_bond_prices() -> None:
    portfolio = MagicMock()
    portfolio.total_amount_currencies = SimpleNamespace(units=100_000, nano=0, currency="rub")
    portfolio.positions = [
        _bond_portfolio_position(current_price_rub=1009, average_price_rub=1005),
    ]

    bond_instrument = MagicMock()
    bond_instrument.nominal = SimpleNamespace(units=1000, nano=0, currency="rub")

    mock_client = MagicMock()
    mock_client.operations.get_portfolio.return_value = portfolio
    mock_client.instruments.bond_by.return_value = MagicMock(instrument=bond_instrument)

    with patch(
        "bond_monitor.infrastructure.tinvest.trading_client._open_client"
    ) as open_client:
        open_client.return_value.__enter__.return_value = mock_client
        snapshot = get_account_snapshot("token", AccountKind.SANDBOX, "acc-1")

    bond = snapshot.bond_positions["TCS00A10AU73"]
    assert float(bond.current_price_pct) == pytest.approx(100.9)
    assert float(bond.average_price_pct) == pytest.approx(100.5)
    assert snapshot.money_rub == Rub(100_000.0)
