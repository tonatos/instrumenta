"""Tests for check_trade_available lookup order."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from bond_monitor.infrastructure.tinvest.read_client import check_trade_available


def test_check_trade_available_prefers_instrument_uid() -> None:
    bond = MagicMock()
    bond.api_trade_available_flag = True
    bond.buy_available_flag = True
    bond.sell_available_flag = True
    bond.figi = "BBG_CANONICAL"
    bond.uid = "uid-from-api"
    bond.lot = 1

    mock_client = MagicMock()
    mock_client.instruments.bond_by.return_value = MagicMock(instrument=bond)

    with patch("t_tech.invest.Client") as client_cls:
        client_cls.return_value.__enter__.return_value = mock_client
        result = check_trade_available(
            "token",
            "BBG_STALE",
            instrument_uid="uid-from-portfolio",
        )

    assert result is not None
    assert result.figi == "BBG_CANONICAL"
    assert result.instrument_uid == "uid-from-api"
    mock_client.instruments.bond_by.assert_called_once()
    call_kwargs = mock_client.instruments.bond_by.call_args.kwargs
    assert call_kwargs["id"] == "uid-from-portfolio"
