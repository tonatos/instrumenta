"""Portfolio and calculator API controllers."""

from __future__ import annotations

from datetime import date

from litestar import Controller, delete, get, patch, post
from litestar.di import Provide
from litestar.exceptions import ClientException, NotFoundException
from litestar.status_codes import HTTP_200_OK, HTTP_201_CREATED, HTTP_204_NO_CONTENT

from bond_monitor.application.bonds.bond_service import BondService
from bond_monitor.application.portfolio.errors import SlotOverrideValidationError
from bond_monitor.application.portfolio.portfolio_service import PortfolioService
from bond_monitor.application.trading.trading_service import TradingService
from bond_monitor.interfaces.api.providers import (
    provide_portfolio_service,
    provide_trading_service,
)
from bond_monitor.domain.portfolio.calculator import calculate_portfolio_budget
from bond_monitor.domain.portfolio.models import RiskProfile
from bond_monitor.domain.portfolio.policies import duration_policy_for_portfolio
from bond_monitor.interfaces.api.controllers.bonds import provide_bond_service
from bond_monitor.interfaces.api.duration_params import parse_rate_scenario
from bond_monitor.interfaces.config import Settings
from bond_monitor.interfaces.schemas.api import (
    AddPositionRequest,
    CalculatorRequest,
    CalculatorResponse,
    ConfigResponse,
    CreatePortfolioRequest,
    PlanResponse,
    PortfolioResponse,
    SetSlotOverrideRequest,
    UpdatePortfolioRequest,
)
from bond_monitor.interfaces.schemas.serializers import plan_to_response, portfolio_to_response


class HealthController(Controller):
    path = "/"

    @get("/health")
    async def health(self) -> dict[str, str]:
        return {"status": "ok"}


class ConfigController(Controller):
    path = "/api/v1/config"

    @get("/")
    async def get_config(self, settings: Settings) -> ConfigResponse:
        return ConfigResponse(
            key_rate=settings.key_rate,
            tax_rate=settings.tax_rate,
            max_days=settings.max_days,
            min_volume_rub=settings.min_volume_rub,
            tinkoff_configured=bool(settings.tinkoff_token),
            sandbox_configured=bool(settings.t_trading_token_sandbox),
            production_configured=bool(settings.t_trading_token_production),
            auth_enabled=settings.auth_enabled,
            telegram_oidc_configured=settings.telegram_oidc_configured,
        )


class PortfoliosController(Controller):
    path = "/api/v1/portfolios"
    dependencies = {
        "portfolio_service": Provide(provide_portfolio_service),
        "bond_service": Provide(provide_bond_service),
        "trading_service": Provide(provide_trading_service),
    }

    @get("/")
    async def list_portfolios(self, portfolio_service: PortfolioService) -> list[PortfolioResponse]:
        portfolios = await portfolio_service.list_portfolios()
        return [portfolio_to_response(p) for p in portfolios]

    @post("/", status_code=HTTP_201_CREATED)
    async def create_portfolio(
        self,
        data: CreatePortfolioRequest,
        portfolio_service: PortfolioService,
    ) -> PortfolioResponse:
        portfolio = await portfolio_service.create_portfolio(
            name=data.name,
            initial_amount_rub=data.initial_amount_rub,
            horizon_date=data.horizon_date,
            risk_profile=RiskProfile(data.risk_profile),
            api_trade_only=data.api_trade_only,
            max_weighted_duration_years=data.max_weighted_duration_years,
            target_duration_years=data.target_duration_years,
        )
        return portfolio_to_response(portfolio)

    @get("/{portfolio_id:str}")
    async def get_portfolio(
        self,
        portfolio_id: str,
        portfolio_service: PortfolioService,
    ) -> PortfolioResponse:
        portfolio = await portfolio_service.get_portfolio(portfolio_id)
        if portfolio is None:
            raise NotFoundException(detail="Portfolio not found")
        return portfolio_to_response(portfolio)

    @delete("/{portfolio_id:str}", status_code=HTTP_204_NO_CONTENT)
    async def delete_portfolio(
        self,
        portfolio_id: str,
        portfolio_service: PortfolioService,
    ) -> None:
        if not await portfolio_service.delete_portfolio(portfolio_id):
            raise NotFoundException(detail="Portfolio not found")

    @patch("/{portfolio_id:str}")
    async def update_portfolio(
        self,
        portfolio_id: str,
        data: UpdatePortfolioRequest,
        portfolio_service: PortfolioService,
    ) -> PortfolioResponse:
        risk_profile = RiskProfile(data.risk_profile) if data.risk_profile else None
        update_kwargs: dict = {
            "name": data.name,
            "initial_amount_rub": data.initial_amount_rub,
            "horizon_date": data.horizon_date,
            "risk_profile": risk_profile,
            "api_trade_only": data.api_trade_only,
        }
        fields_set = data.model_fields_set
        if "max_weighted_duration_years" in fields_set:
            update_kwargs["max_weighted_duration_years"] = data.max_weighted_duration_years
        if "target_duration_years" in fields_set:
            update_kwargs["target_duration_years"] = data.target_duration_years
        try:
            portfolio = await portfolio_service.update_portfolio_fields(
                portfolio_id,
                **update_kwargs,
            )
        except ValueError:
            raise NotFoundException(detail="Portfolio not found")
        return portfolio_to_response(portfolio)

    @post("/{portfolio_id:str}/clear", status_code=HTTP_200_OK)
    async def clear_positions(
        self,
        portfolio_id: str,
        portfolio_service: PortfolioService,
    ) -> PortfolioResponse:
        try:
            portfolio = await portfolio_service.clear_positions(portfolio_id)
        except ValueError:
            raise NotFoundException(detail="Portfolio not found")
        return portfolio_to_response(portfolio)

    @post("/{portfolio_id:str}/positions", status_code=HTTP_200_OK)
    async def add_position(
        self,
        portfolio_id: str,
        data: AddPositionRequest,
        portfolio_service: PortfolioService,
        bond_service: BondService,
    ) -> PortfolioResponse:
        universe = bond_service.load_universe().bonds
        try:
            portfolio = await portfolio_service.add_position(
                portfolio_id,
                universe,
                isin=data.isin,
                lots=data.lots,
                today=date.today(),
            )
        except ValueError as exc:
            message = str(exc)
            if message.startswith("Portfolio"):
                raise NotFoundException(detail="Portfolio not found")
            raise ClientException(detail=message)
        except LookupError:
            raise NotFoundException(detail=f"Bond {data.isin} not found")
        return portfolio_to_response(portfolio)

    @delete("/{portfolio_id:str}/positions/{isin:str}", status_code=HTTP_204_NO_CONTENT)
    async def remove_position(
        self,
        portfolio_id: str,
        isin: str,
        portfolio_service: PortfolioService,
    ) -> None:
        try:
            await portfolio_service.remove_position(portfolio_id, isin)
        except ValueError:
            raise NotFoundException(detail="Portfolio not found")
        except LookupError:
            raise NotFoundException(detail=f"Position {isin} not found")

    @post("/{portfolio_id:str}/slots/override", status_code=HTTP_200_OK)
    async def set_slot_override(
        self,
        portfolio_id: str,
        data: SetSlotOverrideRequest,
        portfolio_service: PortfolioService,
        bond_service: BondService,
        settings: Settings,
        rate_scenario: str | None = None,
    ) -> PortfolioResponse:
        universe = bond_service.load_universe().bonds
        portfolio = await portfolio_service.get_portfolio(portfolio_id)
        if portfolio is None:
            raise NotFoundException(detail="Portfolio not found")
        duration_policy = duration_policy_for_portfolio(
            portfolio,
            rate_scenario=parse_rate_scenario(rate_scenario),
        )
        try:
            portfolio = await portfolio_service.set_slot_override(
                portfolio_id,
                source_position_isin=data.source_position_isin,
                confirmed_isin=data.confirmed_isin,
                universe=universe,
                key_rate=settings.key_rate,
                tax_rate=settings.tax_rate_fraction,
                today=date.today(),
                duration_policy=duration_policy,
            )
        except SlotOverrideValidationError as exc:
            raise ClientException(
                detail=exc.message,
                status_code=422,
                extra={"code": exc.code},
            ) from exc
        except ValueError:
            raise NotFoundException(detail="Portfolio not found") from None
        return portfolio_to_response(portfolio)

    @post("/{portfolio_id:str}/slots/reset-all", status_code=HTTP_200_OK)
    async def reset_all_slot_overrides(
        self,
        portfolio_id: str,
        portfolio_service: PortfolioService,
    ) -> PortfolioResponse:
        try:
            portfolio = await portfolio_service.reset_all_slot_overrides(portfolio_id)
        except ValueError:
            raise NotFoundException(detail="Portfolio not found") from None
        return portfolio_to_response(portfolio)

    @post("/{portfolio_id:str}/auto-compose")
    async def auto_compose(
        self,
        portfolio_id: str,
        portfolio_service: PortfolioService,
        bond_service: BondService,
        settings: Settings,
        rate_scenario: str | None = None,
    ) -> PortfolioResponse:
        portfolio = await portfolio_service.get_portfolio(portfolio_id)
        if portfolio is None:
            raise NotFoundException(detail="Portfolio not found")
        duration_policy = duration_policy_for_portfolio(
            portfolio,
            rate_scenario=parse_rate_scenario(rate_scenario),
        )
        universe = bond_service.load_universe().bonds
        portfolio = await portfolio_service.auto_compose_portfolio(
            portfolio_id,
            universe,
            key_rate=settings.key_rate,
            tax_rate=settings.tax_rate_fraction,
            today=date.today(),
            duration_policy=duration_policy,
        )
        return portfolio_to_response(portfolio)

    @get("/{portfolio_id:str}/plan")
    async def get_plan(
        self,
        portfolio_id: str,
        portfolio_service: PortfolioService,
        bond_service: BondService,
        trading_service: TradingService,
        settings: Settings,
        rate_scenario: str | None = None,
    ) -> PlanResponse:
        universe = bond_service.load_universe().bonds
        portfolio = await portfolio_service.get_portfolio(portfolio_id)
        if portfolio is None:
            raise NotFoundException(detail="Portfolio not found")
        duration_policy = duration_policy_for_portfolio(
            portfolio,
            rate_scenario=parse_rate_scenario(rate_scenario),
        )
        if portfolio.is_trading:
            plan = await trading_service.build_trading_plan(
                portfolio_id,
                universe,
                key_rate=settings.key_rate,
                tax_rate=settings.tax_rate_fraction,
                today=date.today(),
                duration_policy=duration_policy,
            )
        else:
            plan = await portfolio_service.build_portfolio_plan(
                portfolio_id,
                universe,
                key_rate=settings.key_rate,
                tax_rate=settings.tax_rate_fraction,
                today=date.today(),
                duration_policy=duration_policy,
            )
        return plan_to_response(plan)


class CalculatorController(Controller):
    path = "/api/v1/calculator"
    dependencies = {"bond_service": Provide(provide_bond_service)}

    @post("/portfolio")
    async def calculate_portfolio(
        self,
        data: CalculatorRequest,
        bond_service: BondService,
    ) -> CalculatorResponse:
        today = date.today()
        bonds = []
        for secid in data.secids:
            bond = bond_service.load_by_secid(secid)
            if bond is not None:
                bonds.append(bond)
        hold = calculate_portfolio_budget(bonds, budget_rub=data.budget_rub, today=today)
        results = [
            {
                "secid": p.secid,
                "name": p.name,
                "lots": p.lots,
                "invested_rub": p.invested_rub,
                "coupon_income_rub": p.coupon_income_rub,
                "profit_rub": p.profit_rub,
                "hold_days": p.hold_days,
            }
            for p in hold.positions
        ]
        return CalculatorResponse(
            results=results,
            total_invested_rub=hold.total_invested_rub,
            total_profit_rub=hold.total_profit_rub,
            portfolio_yield_pct=hold.portfolio_yield_pct,
        )
