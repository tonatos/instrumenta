"""Core data model for a single bond record."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum, StrEnum

from bond_monitor.domain.shared.formatting import format_date


class CouponType(StrEnum):
    FIXED = "fixed"
    FLOATING = "floating"
    VARIABLE = "variable"
    UNKNOWN = "unknown"


class RiskLevel(int, Enum):
    UNKNOWN = 0
    LOW = 1
    MODERATE = 2
    HIGH = 3


COUPON_TYPE_LABELS: dict[CouponType, str] = {
    CouponType.FIXED: "Фиксированный",
    CouponType.FLOATING: "Плавающий",
    CouponType.VARIABLE: "Переменный",
    CouponType.UNKNOWN: "Неизвестен",
}

RISK_LEVEL_LABELS: dict[RiskLevel, str] = {
    RiskLevel.UNKNOWN: "Неизвестен",
    RiskLevel.LOW: "Низкий",
    RiskLevel.MODERATE: "Умеренный",
    RiskLevel.HIGH: "Высокий",
}

# National rating scale ordinal (higher = better)
RATING_ORDER: dict[str, int] = {
    "ruAAA": 12,
    "AAA": 12,
    "ruAA+": 11,
    "AA+": 11,
    "ruAA": 10,
    "AA": 10,
    "ruAA-": 9,
    "AA-": 9,
    "ruA+": 8,
    "A+": 8,
    "ruA": 7,
    "A": 7,
    "ruA-": 6,
    "A-": 6,
    "ruBBB+": 5,
    "BBB+": 5,
    "ruBBB": 4,
    "BBB": 4,
    "ruBBB-": 3,
    "BBB-": 3,
    "ruBB+": 2,
    "BB+": 2,
    "ruBB": 1,
    "BB": 1,
    "ruBB-": 0,
    "BB-": 0,
    "ruB+": -1,
    "B+": -1,
    "ruB": -2,
    "B": -2,
    "ruB-": -3,
    "B-": -3,
    "ruCCC": -4,
    "CCC": -4,
    "ruCC": -5,
    "CC": -5,
    "ruD": -6,
    "D": -6,
}


@dataclass
class BondRecord:
    # --- Identifiers ---
    secid: str
    isin: str
    figi: str = ""
    name: str = ""

    # --- Dates ---
    maturity_date: date | None = None
    offer_date: date | None = None
    # Окно подачи заявки на пут-оферту (MOEX bondization/offers).
    # ``offer_submission_start`` — с какого дня можно подать заявку эмитенту;
    # ``offer_submission_end`` — крайний срок подачи (часто за 1–2 нед. до
    # ``offer_date``). Если окно уже закрыто, купить бумагу «под оферту»
    # бессмысленно — предъявить уже нельзя.
    offer_submission_start: date | None = None
    offer_submission_end: date | None = None
    # Цена выкупа по пут-оферте, % от номинала (MOEX ``price``). Часто ≠ 100.
    offer_price_pct: float | None = None
    # Effective date: min(maturity_date, offer_date) — the date we actually expect return of principal
    effective_date: date | None = None
    days_to_maturity: int | None = None

    # --- Yield (% per annum) ---
    ytm: float | None = None
    ytm_net: float | None = None  # ytm after НДФЛ (populated by core.scorer.score_bonds)

    # --- Coupon ---
    coupon_rate: float | None = None  # annual coupon rate, %
    accrued_interest: float | None = None  # НКД per bond, RUB
    coupon_type: CouponType = CouponType.UNKNOWN
    coupon_period_days: int | None = None
    next_coupon_date: date | None = None
    coupon_value: float | None = None  # next coupon amount, RUB per bond

    # --- Price ---
    last_price: float | None = None  # % of face value
    face_value: float = 1000.0
    lot_size: int = 1  # bonds per lot

    # --- Duration ---
    duration_days: float | None = None  # Macaulay duration, days

    # --- Liquidity ---
    volume_rub: float | None = None  # today's trading volume (VALTODAY), RUB — for display
    prev_volume_rub: float | None = None  # previous session volume — for liquidity filter/score

    @property
    def filter_volume_rub(self) -> float:
        """Volume for min-liquidity filter and liquidity score (prev session preferred)."""
        if self.prev_volume_rub is not None:
            return self.prev_volume_rub
        return self.volume_rub or 0.0

    @property
    def duration_years(self) -> float | None:
        """Дюрация Маколея в годах.

        Приоритет — значение MOEX (``duration_days``). Если его нет, берём
        срок до погашения как грубую прокси (для короткого carry дюрация ≈
        сроку). Флаг ``duration_is_proxy`` помечает такой случай, чтобы не
        путать прокси с настоящей дюрацией MOEX.
        """
        if self.duration_days is not None:
            return self.duration_days / 365.0
        if self.days_to_maturity is not None and self.days_to_maturity > 0:
            return self.days_to_maturity / 365.0
        return None

    @property
    def duration_is_proxy(self) -> bool:
        """``True`` если ``duration_years`` посчитана из срока, а не из MOEX."""
        return (
            self.duration_days is None
            and self.days_to_maturity is not None
            and self.days_to_maturity > 0
        )

    @property
    def is_floating_coupon(self) -> bool:
        """Плавающий купон (привязан к КС/RUONIA) — низкая чувствительность к ставке."""
        return self.floating_coupon_flag or self.coupon_type == CouponType.FLOATING

    # --- Risk flags (from T-Invest API) ---
    amortization_flag: bool = False
    floating_coupon_flag: bool = False
    perpetual_flag: bool = False
    subordinated_flag: bool = False
    for_qual_investor_flag: bool = False
    liquidity_flag: bool = True
    call_date: date | None = None
    risk_level: RiskLevel = RiskLevel.UNKNOWN

    # --- Default flags (from MOEX ISS /securities/{isin}.json description) ---
    # HASDEFAULT — issuer formally declared in default by MOEX
    # HASTECHNICALDEFAULT — issuer missed a coupon/principal payment but
    # the grace period has not lapsed yet (may resolve without default)
    has_default: bool = False
    has_technical_default: bool = False

    # --- Credit rating (from ratings.json) ---
    credit_rating: str | None = None

    # --- Composite scores [0–100] ---
    score: float | None = None
    ytm_score: float | None = None
    risk_score: float | None = None
    liquidity_score: float | None = None

    # --- Issuer metadata (T-Invest) ---
    issuer_name: str = ""
    instrument_full_name: str = ""
    sector: str = ""
    description: str = ""
    asset_uid: str = ""

    # --- Enrichment metadata ---
    tinvest_enriched: bool = False
    # T-Invest: можно ли торговать через Invest API (PostOrder).
    # None — не обогащено / бумага не найдена в каталоге брокера.
    api_trade_available_flag: bool | None = None

    # --- User state (persisted in cache/favorites.json) ---
    is_favorite: bool = False

    @property
    def has_warnings(self) -> bool:
        return any(
            [
                self.amortization_flag,
                self.floating_coupon_flag,
                self.subordinated_flag,
                self.for_qual_investor_flag,
                self.coupon_type == CouponType.VARIABLE,
                self.call_date is not None,
                self.has_default,
                self.has_technical_default,
            ]
        )

    @property
    def clean_price_rub(self) -> float | None:
        """Clean price in RUB (excluding НКД)."""
        if self.last_price is None:
            return None
        return self.last_price / 100.0 * self.face_value

    @property
    def dirty_price_rub(self) -> float | None:
        """Dirty price in RUB (including НКД)."""
        clean = self.clean_price_rub
        if clean is None:
            return None
        return clean + (self.accrued_interest or 0.0)

    @property
    def price_per_lot_rub(self) -> float | None:
        """Cost to buy one lot (lot_size bonds), dirty price."""
        dirty = self.dirty_price_rub
        if dirty is None:
            return None
        return dirty * self.lot_size

    def warnings_list(self) -> list[str]:
        """Return human-readable list of risk warnings."""
        warnings: list[str] = []
        # Default/technical-default first — these are the strongest red flags
        if self.has_default:
            warnings.append(
                "Эмитент в дефолте (MOEX HASDEFAULT): купоны/номинал не выплачены, "
                "грейс-период истёк. Покупка крайне рискованна"
            )
        if self.has_technical_default:
            warnings.append(
                "Технический дефолт (MOEX HASTECHNICALDEFAULT): эмитент пропустил "
                "выплату, но грейс-период ещё не истёк. Возможен переход в полный дефолт"
            )
        if self.amortization_flag:
            warnings.append(
                "Амортизация: номинал выплачивается частями — реальная доходность ниже купона"
            )
        if self.floating_coupon_flag:
            warnings.append(
                "Плавающий купон: размер купона привязан к КС/RUONIA — доходность непредсказуема"
            )
        if self.coupon_type == CouponType.VARIABLE:
            warnings.append("Переменный купон: следующий купон неизвестен заранее")
        if self.subordinated_flag:
            warnings.append("Субординированная облигация: при банкротстве выплачивается последней")
        if self.for_qual_investor_flag:
            warnings.append("Только для квалифицированных инвесторов")
        if self.call_date is not None:
            warnings.append(
                f"Колл-оферта {format_date(self.call_date)}: эмитент может досрочно выкупить облигацию"
            )
        return warnings
