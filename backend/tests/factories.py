"""Shared test factories — no pytest dependency."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from bond_monitor.domain.bonds.models import BondRecord, RiskLevel
from bond_monitor.domain.portfolio.models import (
    Portfolio,
    PortfolioMode,
    PortfolioPosition,
    PositionSourceType,
    RiskProfile,
)
from bond_monitor.domain.trading.models import (
    AccountKind,
)
from bond_monitor.domain.shared.money import Rub
from bond_monitor.domain.trading.ports import BrokerSnapshot
from bond_monitor.infrastructure.tinvest.trading_client import (
    AccountSnapshot,
    BondPosition,
    OperationRecord,
)

DEFAULT_HORIZON = "2027-01-01"
DEFAULT_PORTFOLIO_PAYLOAD: dict[str, Any] = {
    "initial_amount_rub": 100_000.0,
    "horizon_date": DEFAULT_HORIZON,
    "risk_profile": "normal",
}


def make_bond(
    *,
    isin: str = "RU000ATEST",
    name: str = "Test Bond",
    maturity: date | None = None,
    price: float = 99.0,
    ytm: float = 18.0,
    score: float = 80.0,
    api_trade_available: bool | None = True,
    figi: str | None = None,
    **overrides: Any,
) -> BondRecord:
    maturity = maturity or date(2027, 6, 1)
    bond = BondRecord(
        secid=overrides.pop("secid", isin[:6]),
        isin=isin,
        name=name,
        maturity_date=maturity,
        effective_date=overrides.pop("effective_date", maturity),
        days_to_maturity=overrides.pop(
            "days_to_maturity",
            max((maturity - date.today()).days, 1),
        ),
        last_price=price,
        ytm=ytm,
        ytm_net=overrides.pop("ytm_net", ytm * 0.87),
        score=score,
        ytm_score=overrides.pop("ytm_score", score),
        risk_score=overrides.pop("risk_score", score),
        liquidity_score=overrides.pop("liquidity_score", score),
        risk_level=overrides.pop("risk_level", RiskLevel.LOW),
        credit_rating=overrides.pop("credit_rating", "ruA"),
        lot_size=overrides.pop("lot_size", 1),
        face_value=overrides.pop("face_value", 1000.0),
        volume_rub=overrides.pop("volume_rub", 1_000_000.0),
        api_trade_available_flag=api_trade_available,
        figi=figi,
    )
    for key, value in overrides.items():
        setattr(bond, key, value)
    return bond


def make_live_bond(
    *,
    isin: str,
    name: str,
    maturity: date,
    price: float,
    aci: float = 0.0,
    coupon_rate: float | None = 12.0,
    coupon_period_days: int = 30,
    next_coupon_date: date | None = None,
    ytm: float = 20.0,
    score: float = 85.0,
) -> BondRecord:
    bond = make_bond(
        isin=isin,
        name=name,
        maturity=maturity,
        price=price,
        ytm=ytm,
        score=score,
    )
    bond.accrued_interest = aci
    bond.coupon_rate = coupon_rate
    bond.coupon_period_days = coupon_period_days
    bond.next_coupon_date = next_coupon_date or maturity
    return bond


def make_portfolio(
    *,
    portfolio_id: str = "test-portfolio",
    name: str = "Test Portfolio",
    initial_amount_rub: float = 100_000.0,
    horizon_date: date | None = None,
    risk_profile: RiskProfile = RiskProfile.NORMAL,
    **overrides: Any,
) -> Portfolio:
    return Portfolio(
        id=portfolio_id,
        name=name,
        initial_amount_rub=initial_amount_rub,
        horizon_date=horizon_date or date(2027, 1, 1),
        risk_profile=risk_profile,
        **overrides,
    )


def make_account_snapshot(
    money_rub: float = 150_000.0,
    *,
    account_id: str = "acc-clean",
    account_kind: AccountKind = AccountKind.SANDBOX,
    bond_positions: dict | None = None,
    fetched_at: str | None = None,
) -> BrokerSnapshot:
    return BrokerSnapshot(
        account_id=account_id,
        account_kind=account_kind,
        money_rub=Rub(money_rub),
        bond_positions=bond_positions or {},
        other_instruments=[],
        fetched_at=fetched_at or datetime.now(UTC).isoformat(timespec="seconds"),
    )


def make_infra_account_snapshot(
    money_rub: float = 150_000.0,
    *,
    account_id: str = "acc-clean",
    account_kind: AccountKind = AccountKind.SANDBOX,
    bond_positions: dict[str, BondPosition] | None = None,
    fetched_at: str | None = None,
) -> AccountSnapshot:
    return AccountSnapshot(
        account_id=account_id,
        account_kind=account_kind,
        money_rub=Rub(money_rub),
        bond_positions=bond_positions or {},
        other_instruments=[],
        fetched_at=fetched_at or datetime.now(UTC).isoformat(timespec="seconds"),
    )


def make_snapshot_with_bonds(
    money_rub: float = 50_000.0,
    *,
    account_id: str = "acc-bonds",
) -> AccountSnapshot:
    from bond_monitor.domain.shared.money import PriceUnitPct

    return make_infra_account_snapshot(
        money_rub,
        account_id=account_id,
        bond_positions={
            "BBG0BOND": BondPosition(
                figi="BBG0BOND",
                instrument_uid="uid-1",
                ticker="SU26238",
                quantity=10,
                lots=1,
                blocked=0,
                current_price_pct=PriceUnitPct(95.5),
                current_nkd_rub=Rub(12.0),
                average_price_pct=PriceUnitPct(94.0),
            )
        },
    )


def make_input_operation(
    amount: float,
    *,
    op_id: str = "op-input-1",
    op_date: datetime | None = None,
) -> OperationRecord:
    return OperationRecord(
        id=op_id,
        type="OPERATION_TYPE_INPUT",
        state="EXECUTED",
        date=op_date or datetime.now(UTC),
        figi="",
        instrument_uid="",
        instrument_type="",
        payment_rub=Rub(amount),
        quantity=0,
        price_pct=None,
        commission_rub=None,
    )


def portfolio_create_payload(
    name: str = "Test Portfolio",
    *,
    initial_amount_rub: float = 100_000.0,
    horizon_date: str = DEFAULT_HORIZON,
    risk_profile: str = "normal",
) -> dict[str, Any]:
    return {
        "name": name,
        "initial_amount_rub": initial_amount_rub,
        "horizon_date": horizon_date,
        "risk_profile": risk_profile,
    }


def aa19dfd_portfolio() -> Portfolio:
    today = date(2026, 7, 7)
    return Portfolio(
        id="aa19dfd359c5489988adac94df8bfe8b",
        name="Первый Боевой",
        initial_amount_rub=20_000.0,
        horizon_date=date(2027, 1, 1),
        risk_profile=RiskProfile.AGGRESSIVE,
        cash_balance_rub=2_982.08,
        api_trade_only=True,
        positions=[
            PortfolioPosition(
                isin="RU000A100PB0",
                secid="RU000A100PB0",
                name="ЖКХРСЯ БО1",
                lots=5,
                lot_size=1,
                purchase_clean_price_pct=99.5,
                purchase_dirty_price_rub=1_039.74,
                purchase_aci_rub=44.74,
                purchase_date=today,
                purchase_amount_rub=5_198.7,
                coupon_rate=23.0,
                face_value=1_000.0,
                maturity_date=date(2026, 7, 28),
                offer_date=None,
                coupon_period_days=91,
                next_coupon_date=date(2026, 7, 28),
                source=PositionSourceType.INITIAL,
            ),
            PortfolioPosition(
                isin="RU000A109TG2",
                secid="RU000A109TG2",
                name="iКарРус1P4",
                lots=6,
                lot_size=1,
                purchase_clean_price_pct=96.8,
                purchase_dirty_price_rub=981.36,
                purchase_aci_rub=13.36,
                purchase_date=today,
                purchase_amount_rub=5_888.16,
                coupon_rate=None,
                face_value=1_000.0,
                maturity_date=date(2026, 10, 8),
                offer_date=None,
                coupon_period_days=30,
                next_coupon_date=date(2026, 7, 10),
                source=PositionSourceType.INITIAL,
            ),
            PortfolioPosition(
                isin="RU000A109908",
                secid="RU000A109908",
                name="МВ ФИН 1P5",
                lots=6,
                lot_size=1,
                purchase_clean_price_pct=98.8,
                purchase_dirty_price_rub=988.51,
                purchase_aci_rub=0.51,
                purchase_date=today,
                purchase_amount_rub=5_931.06,
                coupon_rate=None,
                face_value=1_000.0,
                maturity_date=date(2026, 8, 6),
                offer_date=None,
                coupon_period_days=30,
                next_coupon_date=date(2026, 8, 6),
                source=PositionSourceType.INITIAL,
            ),
        ],
    )


def aa19dfd_universe() -> list[BondRecord]:
    return [
        make_live_bond(
            isin="RU000A100PB0",
            name="ЖКХРСЯ БО1",
            maturity=date(2026, 7, 28),
            price=99.5,
            aci=44.74,
            coupon_rate=23.0,
            coupon_period_days=91,
            next_coupon_date=date(2026, 7, 28),
        ),
        make_live_bond(
            isin="RU000A109TG2",
            name="iКарРус1P4",
            maturity=date(2026, 10, 8),
            price=96.8,
            aci=13.36,
            coupon_rate=None,
            coupon_period_days=30,
            next_coupon_date=date(2026, 7, 10),
            ytm=24.0,
            score=95.0,
        ),
        make_live_bond(
            isin="RU000A109908",
            name="МВ ФИН 1P5",
            maturity=date(2026, 8, 6),
            price=98.8,
            aci=0.51,
            coupon_rate=None,
            coupon_period_days=30,
            next_coupon_date=date(2026, 8, 6),
        ),
        make_live_bond(
            isin="RU000A107BH2",
            name="ИЛСБО-1-1Р",
            maturity=date(2026, 11, 19),
            price=94.5,
            aci=5.0,
            ytm=18.0,
            score=82.0,
        ),
        make_live_bond(
            isin="RU000A1074E7",
            name="РУССОЙЛ-01",
            maturity=date(2026, 10, 20),
            price=99.8,
            aci=1.0,
            ytm=19.0,
            score=88.0,
        ),
        make_live_bond(
            isin="RU000A107G22",
            name="КОРПСАН 01",
            maturity=date(2026, 12, 18),
            price=95.0,
            aci=3.0,
            ytm=21.0,
            score=87.0,
        ),
        make_live_bond(
            isin="RU000A107KR2",
            name="МигКр 04",
            maturity=date(2026, 12, 31),
            price=96.0,
            aci=2.0,
            ytm=20.0,
            score=86.0,
        ),
    ]


_AA19DFD_LIVE_TODAY = date(2026, 7, 8)


def aa19dfd_live_portfolio() -> Portfolio:
    """Live trading portfolio aa19dfd (8 позиций, snapshot 2026-07-10)."""
    return Portfolio(
        id="aa19dfd359c5489988adac94df8bfe8b",
        name="Первый Боевой",
        initial_amount_rub=20_000.0,
        horizon_date=date(2027, 1, 1),
        risk_profile=RiskProfile.AGGRESSIVE,
        cash_balance_rub=632.14,
        api_trade_only=True,
        mode=PortfolioMode.TRADING,
        positions=[
            PortfolioPosition(
                isin="RU000A100PB0",
                secid="RU000A100PB0",
                name="ЖКХРСЯ БО1",
                lots=5,
                lot_size=1,
                purchase_clean_price_pct=99.5,
                purchase_dirty_price_rub=1_039.74,
                purchase_aci_rub=44.74,
                purchase_date=date(2026, 7, 7),
                purchase_amount_rub=5_198.7,
                coupon_rate=23.0,
                face_value=1_000.0,
                maturity_date=date(2026, 7, 28),
                offer_date=None,
                coupon_period_days=91,
                next_coupon_date=date(2026, 7, 28),
                source=PositionSourceType.INITIAL,
            ),
            PortfolioPosition(
                isin="RU000A109908",
                secid="RU000A109908",
                name="МВ ФИН 1P5",
                lots=26,
                lot_size=1,
                purchase_clean_price_pct=98.79,
                purchase_dirty_price_rub=988.41,
                purchase_aci_rub=0.51,
                purchase_date=date(2026, 7, 7),
                purchase_amount_rub=5_930.46,
                coupon_rate=None,
                face_value=1_000.0,
                maturity_date=date(2026, 8, 6),
                offer_date=None,
                coupon_period_days=30,
                next_coupon_date=date(2026, 8, 6),
                source=PositionSourceType.INITIAL,
            ),
            PortfolioPosition(
                isin="RU000A106UB7",
                secid="RU000A106UB7",
                name="Кириллица3",
                lots=34,
                lot_size=1,
                purchase_clean_price_pct=98.37,
                purchase_dirty_price_rub=990.48,
                purchase_aci_rub=6.78,
                purchase_date=_AA19DFD_LIVE_TODAY,
                purchase_amount_rub=33_676.32,
                coupon_rate=16.5,
                face_value=1_000.0,
                maturity_date=date(2026, 8, 22),
                offer_date=None,
                coupon_period_days=30,
                next_coupon_date=date(2026, 7, 23),
                source=PositionSourceType.INITIAL,
            ),
            PortfolioPosition(
                isin="RU000A107G22",
                secid="RU000A107G22",
                name="КОРПСАН 01",
                lots=37,
                lot_size=1,
                purchase_clean_price_pct=90.68,
                purchase_dirty_price_rub=914.61,
                purchase_aci_rub=7.81,
                purchase_date=_AA19DFD_LIVE_TODAY,
                purchase_amount_rub=33_840.57,
                coupon_rate=15.0,
                face_value=1_000.0,
                maturity_date=date(2026, 12, 18),
                offer_date=None,
                coupon_period_days=91,
                next_coupon_date=date(2026, 9, 18),
                source=PositionSourceType.INITIAL,
            ),
            PortfolioPosition(
                isin="RU000A103WB0",
                secid="RU000A103WB0",
                name="СлавЭКО1Р1",
                lots=34,
                lot_size=1,
                purchase_clean_price_pct=94.9,
                purchase_dirty_price_rub=974.62,
                purchase_aci_rub=25.62,
                purchase_date=_AA19DFD_LIVE_TODAY,
                purchase_amount_rub=33_137.08,
                coupon_rate=11.0,
                face_value=1_000.0,
                maturity_date=date(2026, 10, 13),
                offer_date=None,
                coupon_period_days=91,
                next_coupon_date=date(2026, 7, 14),
                source=PositionSourceType.INITIAL,
            ),
            PortfolioPosition(
                isin="RU000A109TG2",
                secid="RU000A109TG2",
                name="iКарРус1P4",
                lots=40,
                lot_size=1,
                purchase_clean_price_pct=96.89,
                purchase_dirty_price_rub=982.26,
                purchase_aci_rub=13.36,
                purchase_date=_AA19DFD_LIVE_TODAY,
                purchase_amount_rub=35_361.36,
                coupon_rate=None,
                face_value=1_000.0,
                maturity_date=date(2026, 10, 8),
                offer_date=None,
                coupon_period_days=30,
                next_coupon_date=date(2026, 7, 10),
                source=PositionSourceType.ADOPTED,
            ),
            PortfolioPosition(
                isin="RU000A106YN4",
                secid="RU000A106YN4",
                name="ГрупПро1P3",
                lots=33,
                lot_size=1,
                purchase_clean_price_pct=98.14,
                purchase_dirty_price_rub=991.92,
                purchase_aci_rub=10.52,
                purchase_date=_AA19DFD_LIVE_TODAY,
                purchase_amount_rub=48_604.08,
                coupon_rate=16.0,
                face_value=1_000.0,
                maturity_date=date(2026, 9, 12),
                offer_date=None,
                coupon_period_days=30,
                next_coupon_date=date(2026, 7, 14),
                source=PositionSourceType.ADOPTED,
            ),
            PortfolioPosition(
                isin="RU000A106VN0",
                secid="RU000A106VN0",
                name="ТРДБ Б0-01",
                lots=42,
                lot_size=1,
                purchase_clean_price_pct=99.1,
                purchase_dirty_price_rub=996.42,
                purchase_aci_rub=5.42,
                purchase_date=_AA19DFD_LIVE_TODAY,
                purchase_amount_rub=41_849.64,
                coupon_rate=18.0,
                face_value=1_000.0,
                maturity_date=date(2026, 8, 27),
                offer_date=None,
                coupon_period_days=30,
                next_coupon_date=date(2026, 7, 28),
                source=PositionSourceType.ADOPTED,
            ),
        ],
    )


def aa19dfd_live_universe() -> list[BondRecord]:
    """Universe для live aa19dfd: держимые бумаги + кандидаты реинвеста."""
    base = {bond.isin: bond for bond in aa19dfd_universe()}
    extra_specs = [
        ("RU000A106UB7", "Кириллица3", date(2026, 8, 22), 98.37, 6.78, 16.5, date(2026, 7, 23)),
        ("RU000A103WB0", "СлавЭКО1Р1", date(2026, 10, 13), 94.9, 25.62, 11.0, date(2026, 7, 14)),
        ("RU000A106YN4", "ГрупПро1P3", date(2026, 9, 12), 98.14, 10.52, 16.0, date(2026, 7, 14)),
        ("RU000A106VN0", "ТРДБ Б0-01", date(2026, 8, 27), 99.1, 5.42, 18.0, date(2026, 7, 28)),
        ("RU000A108A01", "НовТех1Р2", date(2027, 3, 1), 95.0, 2.0, 22.0, date(2026, 10, 1)),
        ("RU000A108A02", "БинФарм1P3", date(2027, 3, 15), 96.0, 2.0, 21.0, date(2026, 10, 1)),
        ("RU000A108A03", "Джи-гр 2Р4", date(2027, 4, 1), 94.0, 2.0, 20.0, date(2026, 10, 1)),
        ("RU000A108A04", "Джой 1P1", date(2027, 4, 15), 93.0, 2.0, 19.0, date(2026, 10, 1)),
        ("RU000A108A05", "Аэрфью2Р02", date(2027, 5, 1), 97.0, 2.0, 23.0, date(2026, 10, 1)),
        ("RU000A108A06", "ИнтЛиз1Р06", date(2027, 5, 15), 95.5, 2.0, 18.0, date(2026, 10, 1)),
        ("RU000A108A07", "ИнтЛиз1Р07", date(2027, 6, 1), 95.0, 2.0, 17.0, date(2026, 10, 1)),
        ("RU000A108A08", "АйДиКоле06", date(2026, 11, 21), 99.0, 1.0, 16.0, date(2026, 10, 1)),
        ("RU000A108A09", "СПбГО35002", date(2027, 2, 1), 98.0, 1.0, 15.0, date(2026, 10, 1)),
        ("RU000A108A10", "iПозитивР2", date(2027, 3, 20), 94.5, 2.0, 20.0, date(2026, 10, 1)),
        ("RU000A108A11", "СКЛиз1Р01", date(2027, 2, 15), 96.5, 1.0, 16.0, date(2026, 10, 1)),
        ("RU000A108A12", "Реиннол1P2", date(2027, 4, 10), 92.0, 2.0, 22.0, date(2026, 10, 1)),
    ]
    for isin, name, maturity, price, aci, coupon_rate, next_coupon in extra_specs:
        if isin not in base:
            base[isin] = make_live_bond(
                isin=isin,
                name=name,
                maturity=maturity,
                price=price,
                aci=aci,
                coupon_rate=coupon_rate,
                coupon_period_days=30,
                next_coupon_date=next_coupon,
                ytm=20.0,
                score=90.0,
            )
    # held bonds with live prices
    base["RU000A107G22"] = make_live_bond(
        isin="RU000A107G22",
        name="КОРПСАН 01",
        maturity=date(2026, 12, 18),
        price=90.68,
        aci=7.81,
        coupon_rate=15.0,
        coupon_period_days=91,
        next_coupon_date=date(2026, 9, 18),
        ytm=21.0,
        score=87.0,
    )
    base["RU000A109TG2"] = make_live_bond(
        isin="RU000A109TG2",
        name="iКарРус1P4",
        maturity=date(2026, 10, 8),
        price=96.89,
        aci=13.36,
        coupon_rate=None,
        coupon_period_days=30,
        next_coupon_date=date(2026, 7, 10),
        ytm=24.0,
        score=95.0,
    )
    return list(base.values())
