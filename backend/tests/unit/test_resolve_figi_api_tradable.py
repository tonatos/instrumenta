"""resolve_figi_for_isin должен выбирать API-торгуемый инструмент при дублях ISIN."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from bond_monitor.infrastructure.tinvest.read_client import resolve_figi_for_isin


def _instrument(figi: str, *, api_trade: bool) -> MagicMock:
    inst = MagicMock()
    inst.isin = "RU000A100PB0"
    inst.figi = figi
    inst.api_trade_available_flag = api_trade
    return inst


def test_resolve_figi_prefers_api_tradable_among_isin_matches() -> None:
    stale = _instrument("TCSM51800PB0", api_trade=False)
    tradable = _instrument("BBGYAKUTV001", api_trade=True)
    mock_client = MagicMock()
    mock_client.instruments.find_instrument.return_value = MagicMock(
        instruments=[stale, tradable],
    )

    with patch("t_tech.invest.Client") as client_cls:
        client_cls.return_value.__enter__.return_value = mock_client
        figi = resolve_figi_for_isin("token", "RU000A100PB0")

    assert figi == "BBGYAKUTV001"
