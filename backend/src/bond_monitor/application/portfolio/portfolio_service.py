"""Portfolio application services."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from bond_monitor.application.portfolio.errors import SlotOverrideValidationError
from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.models import Portfolio, RiskProfile
from bond_monitor.domain.portfolio.planner import (
    PortfolioPlan,
    auto_compose,
    build_plan,
    clear_downstream_slot_overrides,
    distribute_top_up,
    validate_slot_replacement,
)
from bond_monitor.infrastructure.persistence.repository import PortfolioRepository


class PortfolioService:
    """CRUD and planning operations for portfolios."""

    def __init__(self, repo: PortfolioRepository) -> None:
        self._repo = repo

    async def list_portfolios(self) -> list[Portfolio]:
        return await self._repo.list_all()

    async def get_portfolio(self, portfolio_id: str) -> Portfolio | None:
        return await self._repo.get_by_id(portfolio_id)

    async def create_portfolio(
        self,
        *,
        name: str,
        initial_amount_rub: float,
        horizon_date: date,
        risk_profile: RiskProfile,
        api_trade_only: bool = True,
    ) -> Portfolio:
        portfolio = Portfolio(
            id=uuid4().hex,
            name=name,
            initial_amount_rub=initial_amount_rub,
            horizon_date=horizon_date,
            risk_profile=risk_profile,
            api_trade_only=api_trade_only,
        )
        return await self._repo.save(portfolio)

    async def update_portfolio(self, portfolio: Portfolio) -> Portfolio:
        return await self._repo.save(portfolio)

    async def delete_portfolio(self, portfolio_id: str) -> bool:
        return await self._repo.delete(portfolio_id)

    async def auto_compose_portfolio(
        self,
        portfolio_id: str,
        universe: list[BondRecord],
        *,
        key_rate: float,
        tax_rate: float,
        today: date,
    ) -> Portfolio:
        portfolio = await self._repo.get_by_id(portfolio_id)
        if portfolio is None:
            raise ValueError(f"Portfolio {portfolio_id} not found")
        positions, remaining_cash, _notes = auto_compose(
            initial_amount=portfolio.initial_amount_rub,
            universe=universe,
            profile=portfolio.risk_profile,
            horizon_date=portfolio.horizon_date,
            today=today,
            key_rate=key_rate,
            tax_rate=tax_rate,
            api_trade_only=portfolio.api_trade_only,
        )
        portfolio.positions = positions
        portfolio.cash_balance_rub = remaining_cash
        return await self._repo.save(portfolio)

    async def build_portfolio_plan(
        self,
        portfolio_id: str,
        universe: list[BondRecord],
        *,
        key_rate: float,
        tax_rate: float,
        today: date,
        tax_rate_fraction: float | None = None,
        account_snapshot_money_rub: float | None = None,
        assume_best_put_outcome: bool = True,
    ) -> PortfolioPlan:
        portfolio = await self._repo.get_by_id(portfolio_id)
        if portfolio is None:
            raise ValueError(f"Portfolio {portfolio_id} not found")
        if portfolio.is_trading and account_snapshot_money_rub is None:
            account_snapshot_money_rub = portfolio.cash_balance_rub
            assume_best_put_outcome = False
        plan = build_plan(
            portfolio,
            universe,
            today=today,
            key_rate=key_rate,
            tax_rate=tax_rate,
            assume_best_put_outcome=assume_best_put_outcome,
            account_snapshot_money_rub=account_snapshot_money_rub,
        )
        # Persist if slot overrides were cleared during planning
        await self._repo.save(portfolio)
        return plan

    async def update_portfolio_fields(
        self,
        portfolio_id: str,
        *,
        name: str | None = None,
        initial_amount_rub: float | None = None,
        horizon_date: date | None = None,
        risk_profile: RiskProfile | None = None,
        api_trade_only: bool | None = None,
    ) -> Portfolio:
        portfolio = await self._repo.get_by_id(portfolio_id)
        if portfolio is None:
            raise ValueError(f"Portfolio {portfolio_id} not found")
        if name is not None:
            portfolio.name = name
        if initial_amount_rub is not None:
            portfolio.initial_amount_rub = initial_amount_rub
        if horizon_date is not None:
            portfolio.horizon_date = horizon_date
        if risk_profile is not None:
            portfolio.risk_profile = risk_profile
        if api_trade_only is not None:
            portfolio.api_trade_only = api_trade_only
        portfolio.touch()
        return await self._repo.save(portfolio)

    async def add_position(
        self,
        portfolio_id: str,
        universe: list[BondRecord],
        *,
        isin: str,
        lots: int,
        today: date,
    ) -> Portfolio:
        from bond_monitor.domain.portfolio.planner import position_from_bond

        portfolio = await self._repo.get_by_id(portfolio_id)
        if portfolio is None:
            raise ValueError(f"Portfolio {portfolio_id} not found")
        bond = next((b for b in universe if b.isin == isin), None)
        if bond is None:
            raise LookupError(f"Bond {isin} not found in universe")
        if portfolio.api_trade_only and bond.api_trade_available_flag is not True:
            raise ValueError(
                f"Облигация {isin} недоступна для торговли через T-Invest API. "
                f"Отключите фильтр «только API-торгуемые» в настройках портфеля "
                f"или выберите другую бумагу."
            )
        position = position_from_bond(bond, lots=lots, purchase_date=today)
        purchase_amount = position.purchase_amount_rub
        portfolio.positions.append(position)
        portfolio.cash_balance_rub = max(0.0, portfolio.cash_balance_rub - purchase_amount)
        portfolio.touch()
        return await self._repo.save(portfolio)

    async def remove_position(
        self,
        portfolio_id: str,
        isin: str,
    ) -> Portfolio:
        portfolio = await self._repo.get_by_id(portfolio_id)
        if portfolio is None:
            raise ValueError(f"Portfolio {portfolio_id} not found")
        original_len = len(portfolio.positions)
        portfolio.positions = [p for p in portfolio.positions if p.isin != isin]
        if len(portfolio.positions) == original_len:
            raise LookupError(f"Position with ISIN {isin} not found in portfolio")
        portfolio.touch()
        return await self._repo.save(portfolio)

    async def clear_positions(
        self,
        portfolio_id: str,
    ) -> Portfolio:
        portfolio = await self._repo.get_by_id(portfolio_id)
        if portfolio is None:
            raise ValueError(f"Portfolio {portfolio_id} not found")
        portfolio.positions = []
        portfolio.slots = []
        portfolio.cash_balance_rub = portfolio.initial_amount_rub
        portfolio.touch()
        return await self._repo.save(portfolio)

    async def set_slot_override(
        self,
        portfolio_id: str,
        *,
        source_position_isin: str,
        confirmed_isin: str | None,
        universe: list[BondRecord],
        key_rate: float,
        tax_rate: float,
        today: date,
    ) -> Portfolio:
        from bond_monitor.domain.portfolio.models import (
    ReinvestmentSlot,
    ReinvestmentTriggerReason,
)

        portfolio = await self._repo.get_by_id(portfolio_id)
        if portfolio is None:
            raise ValueError(f"Portfolio {portfolio_id} not found")

        plan = build_plan(
            portfolio,
            universe,
            today=today,
            key_rate=key_rate,
            tax_rate=tax_rate,
        )
        matching_slots = [
            slot
            for slot in plan.resolved_slots
            if slot.source_position_isin == source_position_isin
        ]
        slot_context = matching_slots[0] if matching_slots else None

        if confirmed_isin is not None:
            if slot_context is None:
                raise SlotOverrideValidationError(
                    "Слот реинвестиции для этой позиции не найден в плане"
                )
            reason = validate_slot_replacement(
                portfolio,
                universe,
                slot=slot_context,
                confirmed_isin=confirmed_isin,
                key_rate=key_rate,
                tax_rate=tax_rate,
            )
            if reason is not None:
                raise SlotOverrideValidationError(reason)

        previous_confirmed: str | None = None
        for slot in portfolio.slots:
            if slot.source_position_isin == source_position_isin:
                previous_confirmed = slot.confirmed_isin
                break

        if confirmed_isin != previous_confirmed:
            clear_downstream_slot_overrides(
                portfolio,
                source_position_isin,
                plan.resolved_slots,
            )

        for slot in portfolio.slots:
            if slot.source_position_isin == source_position_isin:
                slot.confirmed_isin = confirmed_isin
                portfolio.touch()
                return await self._repo.save(portfolio)

        portfolio.slots.append(
            ReinvestmentSlot(
                trigger_date=date.today(),
                trigger_reason=ReinvestmentTriggerReason.MATURITY,
                expected_cash_rub=0.0,
                confirmed_isin=confirmed_isin,
                source_position_isin=source_position_isin,
            )
        )
        portfolio.touch()
        return await self._repo.save(portfolio)

    async def reset_all_slot_overrides(self, portfolio_id: str) -> Portfolio:
        portfolio = await self._repo.get_by_id(portfolio_id)
        if portfolio is None:
            raise ValueError(f"Portfolio {portfolio_id} not found")

        changed = False
        for slot in portfolio.slots:
            if slot.confirmed_isin is not None:
                slot.confirmed_isin = None
                changed = True
        if changed:
            portfolio.touch()
            return await self._repo.save(portfolio)
        return portfolio

    async def preview_top_up(
        self,
        portfolio_id: str,
        universe: list[BondRecord],
        amount_rub: float,
        *,
        key_rate: float,
        tax_rate: float,
        today: date,
    ):
        portfolio = await self._repo.get_by_id(portfolio_id)
        if portfolio is None:
            raise ValueError(f"Portfolio {portfolio_id} not found")
        return distribute_top_up(
            portfolio=portfolio,
            universe=universe,
            top_up_amount_rub=amount_rub,
            today=today,
            key_rate=key_rate,
            tax_rate=tax_rate,
        )
