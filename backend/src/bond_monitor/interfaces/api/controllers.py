"""Litestar API controllers."""

from __future__ import annotations

from datetime import date

from litestar import Controller, delete, get, patch, post, put
from litestar.di import Provide
from litestar.exceptions import ClientException, NotFoundException
from litestar.status_codes import HTTP_200_OK, HTTP_201_CREATED, HTTP_204_NO_CONTENT
from sqlalchemy.ext.asyncio import AsyncSession

from bond_monitor.application.bonds.bond_service import BondService
from bond_monitor.application.portfolio.errors import SlotOverrideValidationError
from bond_monitor.application.portfolio.portfolio_service import PortfolioService
from bond_monitor.application.trading.trading_service import TradingService
from bond_monitor.domain.portfolio.calculator import calculate_portfolio_budget
from bond_monitor.domain.portfolio.models import RiskProfile
from bond_monitor.infrastructure.persistence.database import get_db_session
from bond_monitor.infrastructure.persistence.favorites_repository import FavoritesRepository
from bond_monitor.infrastructure.persistence.repository import PortfolioRepository
from bond_monitor.interfaces.config import Settings, get_settings
from bond_monitor.interfaces.schemas.api import (
    AccountOperationsResponse,
    AccountPreviewResponse,
    AddPositionRequest,
    BondsListResponse,
    BrokerAccountResponse,
    CalculatorRequest,
    CalculatorResponse,
    ClearAccountRequest,
    ConfigResponse,
    ConfirmPendingRequest,
    CreatePortfolioRequest,
    CreateSandboxAccountRequest,
    DeleteSandboxAccountResponse,
    OrderPreviewResponse,
    PlanResponse,
    PortfolioResponse,
    PutOfferDecisionRequest,
    SandboxPayInRequest,
    SandboxPayInResponse,
    SetSlotOverrideRequest,
    TradingSyncResponse,
    UpdatePortfolioRequest,
)
from bond_monitor.interfaces.schemas.serializers import (
    account_operation_to_response,
    bond_to_response,
    plan_to_response,
    portfolio_to_response,
)


def provide_bond_service(settings: Settings) -> BondService:
    return BondService(
        key_rate=settings.key_rate,
        tax_rate=settings.tax_rate / 100.0,
        tinkoff_token=settings.tinkoff_token,
        max_days=settings.max_days,
        min_volume_rub=settings.min_volume_rub,
    )


async def provide_portfolio_service(db_session: AsyncSession) -> PortfolioService:
    return PortfolioService(PortfolioRepository(db_session))


async def provide_favorites_repo(db_session: AsyncSession) -> FavoritesRepository:
    return FavoritesRepository(db_session)


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
        )


class BondsController(Controller):
    path = "/api/v1/bonds"
    dependencies = {
        "bond_service": Provide(provide_bond_service),
        "favorites_repo": Provide(provide_favorites_repo),
    }

    @get("/")
    async def list_bonds(
        self,
        bond_service: BondService,
        favorites_repo: FavoritesRepository,
        filter_by: str = "effective",
    ) -> BondsListResponse:
        result = bond_service.load_screener_bonds(filter_by=filter_by)
        favorite_isins = set(await favorites_repo.list_isins())
        bonds = []
        for b in result.bonds:
            b.is_favorite = b.isin in favorite_isins
            bonds.append(bond_to_response(b))
        return BondsListResponse(bonds=bonds, source=result.source, count=len(bonds))

    @get("/{secid:str}")
    async def get_bond(
        self,
        secid: str,
        bond_service: BondService,
        favorites_repo: FavoritesRepository,
    ) -> dict:
        bond = bond_service.load_by_secid(secid)
        if bond is None:
            from litestar.exceptions import NotFoundException

            raise NotFoundException(detail=f"Bond {secid} not found")
        favorite_isins = set(await favorites_repo.list_isins())
        bond.is_favorite = bond.isin in favorite_isins
        coupons = bond_service.get_coupon_schedule(bond.figi) if bond.figi else []
        return {"bond": bond_to_response(bond), "coupons": coupons}

    @post("/refresh")
    async def refresh_bonds(self) -> dict[str, str]:
        from bond_monitor.infrastructure.moex.client import invalidate_moex_cache

        invalidate_moex_cache()
        return {"status": "ok"}


class FavoritesController(Controller):
    path = "/api/v1/favorites"
    dependencies = {
        "favorites_repo": Provide(provide_favorites_repo),
        "bond_service": Provide(provide_bond_service),
    }

    @get("/")
    async def list_favorites(
        self,
        favorites_repo: FavoritesRepository,
        bond_service: BondService,
    ) -> BondsListResponse:
        isins = await favorites_repo.list_isins()
        bonds = bond_service.load_by_isins(isins)
        for b in bonds:
            b.is_favorite = True
        return BondsListResponse(
            bonds=[bond_to_response(b) for b in bonds],
            source="favorites",
            count=len(bonds),
        )

    @put("/{isin:str}", status_code=HTTP_201_CREATED)
    async def add_favorite(self, isin: str, favorites_repo: FavoritesRepository) -> dict[str, str]:
        await favorites_repo.add(isin)
        return {"isin": isin, "status": "added"}

    @delete("/{isin:str}", status_code=HTTP_204_NO_CONTENT)
    async def remove_favorite(self, isin: str, favorites_repo: FavoritesRepository) -> None:
        await favorites_repo.remove(isin)


class PortfoliosController(Controller):
    path = "/api/v1/portfolios"
    dependencies = {
        "portfolio_service": Provide(provide_portfolio_service),
        "bond_service": Provide(provide_bond_service),
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
            from litestar.exceptions import NotFoundException

            raise NotFoundException(detail="Portfolio not found")
        return portfolio_to_response(portfolio)

    @delete("/{portfolio_id:str}", status_code=HTTP_204_NO_CONTENT)
    async def delete_portfolio(
        self,
        portfolio_id: str,
        portfolio_service: PortfolioService,
    ) -> None:
        if not await portfolio_service.delete_portfolio(portfolio_id):
            from litestar.exceptions import NotFoundException

            raise NotFoundException(detail="Portfolio not found")

    @patch("/{portfolio_id:str}")
    async def update_portfolio(
        self,
        portfolio_id: str,
        data: UpdatePortfolioRequest,
        portfolio_service: PortfolioService,
    ) -> PortfolioResponse:
        risk_profile = RiskProfile(data.risk_profile) if data.risk_profile else None
        try:
            portfolio = await portfolio_service.update_portfolio_fields(
                portfolio_id,
                name=data.name,
                initial_amount_rub=data.initial_amount_rub,
                horizon_date=data.horizon_date,
                risk_profile=risk_profile,
                api_trade_only=data.api_trade_only,
            )
        except ValueError:
            from litestar.exceptions import NotFoundException

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
            from litestar.exceptions import NotFoundException

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
            from litestar.exceptions import ClientException, NotFoundException

            message = str(exc)
            if message.startswith("Portfolio"):
                raise NotFoundException(detail="Portfolio not found")
            raise ClientException(detail=message)
        except LookupError:
            from litestar.exceptions import NotFoundException

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
            from litestar.exceptions import NotFoundException

            raise NotFoundException(detail="Portfolio not found")
        except LookupError:
            from litestar.exceptions import NotFoundException

            raise NotFoundException(detail=f"Position {isin} not found")

    @post("/{portfolio_id:str}/slots/override", status_code=HTTP_200_OK)
    async def set_slot_override(
        self,
        portfolio_id: str,
        data: SetSlotOverrideRequest,
        portfolio_service: PortfolioService,
        bond_service: BondService,
        settings: Settings,
    ) -> PortfolioResponse:
        universe = bond_service.load_universe().bonds
        try:
            portfolio = await portfolio_service.set_slot_override(
                portfolio_id,
                source_position_isin=data.source_position_isin,
                confirmed_isin=data.confirmed_isin,
                universe=universe,
                key_rate=settings.key_rate,
                tax_rate=settings.tax_rate / 100.0,
                today=date.today(),
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
    ) -> PortfolioResponse:
        universe = bond_service.load_universe().bonds
        portfolio = await portfolio_service.auto_compose_portfolio(
            portfolio_id,
            universe,
            key_rate=settings.key_rate,
            tax_rate=settings.tax_rate / 100.0,
            today=date.today(),
        )
        return portfolio_to_response(portfolio)

    @get("/{portfolio_id:str}/plan")
    async def get_plan(
        self,
        portfolio_id: str,
        portfolio_service: PortfolioService,
        bond_service: BondService,
        settings: Settings,
    ) -> PlanResponse:
        universe = bond_service.load_universe().bonds
        plan = await portfolio_service.build_portfolio_plan(
            portfolio_id,
            universe,
            key_rate=settings.key_rate,
            tax_rate=settings.tax_rate / 100.0,
            today=date.today(),
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


class RatingsController(Controller):
    path = "/api/v1/ratings"
    dependencies = {"bond_service": Provide(provide_bond_service)}

    @post("/refresh")
    async def refresh_ratings(self, bond_service: BondService) -> dict[str, int]:
        count = bond_service.refresh_ratings()
        return {"count": count}


async def provide_trading_service(
    db_session: AsyncSession,
    settings: Settings,
) -> TradingService:
    return TradingService(
        PortfolioRepository(db_session),
        sandbox_token=settings.t_trading_token_sandbox,
        production_token=settings.t_trading_token_production,
    )


class TradingController(Controller):
    path = "/api/v1"
    dependencies = {
        "trading_service": Provide(provide_trading_service),
        "bond_service": Provide(provide_bond_service),
    }

    @get("/accounts")
    async def list_accounts(
        self,
        trading_service: TradingService,
        kind: str = "sandbox",
    ) -> list[dict]:
        from bond_monitor.domain.portfolio.models import AccountKind

        return await trading_service.list_accounts(AccountKind(kind))

    @post("/accounts/sandbox", status_code=HTTP_201_CREATED)
    async def create_sandbox_account(
        self,
        data: CreateSandboxAccountRequest,
        trading_service: TradingService,
    ) -> BrokerAccountResponse:
        from litestar.exceptions import ClientException

        try:
            account = await trading_service.create_sandbox_account(
                initial_amount_rub=data.initial_amount_rub,
                name=data.name,
            )
        except ValueError as exc:
            raise ClientException(detail=str(exc)) from exc
        return BrokerAccountResponse(**account)

    @delete("/accounts/sandbox/{account_id:str}", status_code=HTTP_200_OK)
    async def delete_sandbox_account(
        self,
        account_id: str,
        trading_service: TradingService,
    ) -> DeleteSandboxAccountResponse:
        from litestar.exceptions import ClientException

        try:
            result = await trading_service.delete_sandbox_account(account_id)
        except ValueError as exc:
            raise ClientException(detail=str(exc)) from exc
        return DeleteSandboxAccountResponse(**result)

    @get("/portfolios/{portfolio_id:str}/account-preview")
    async def account_preview(
        self,
        portfolio_id: str,
        trading_service: TradingService,
        account_id: str,
        kind: str = "sandbox",
    ) -> AccountPreviewResponse:
        from litestar.exceptions import ClientException, NotFoundException

        from bond_monitor.domain.portfolio.models import AccountKind

        try:
            preview = await trading_service.get_account_preview(
                portfolio_id,
                account_id=account_id,
                kind=AccountKind(kind),
            )
        except ValueError as exc:
            message = str(exc)
            if message == "Portfolio not found":
                raise NotFoundException(detail=message)
            raise ClientException(detail=message)
        return AccountPreviewResponse(**preview)

    @post("/portfolios/{portfolio_id:str}/clear-account", status_code=HTTP_200_OK)
    async def clear_account(
        self,
        portfolio_id: str,
        data: ClearAccountRequest,
        trading_service: TradingService,
    ) -> AccountPreviewResponse:
        from litestar.exceptions import ClientException, NotFoundException

        from bond_monitor.domain.portfolio.models import AccountKind

        try:
            preview = await trading_service.clear_account_for_attach(
                portfolio_id,
                account_id=data.account_id,
                kind=AccountKind(data.kind),
                pay_in_rub=data.pay_in_rub,
            )
        except ValueError as exc:
            message = str(exc)
            if message == "Portfolio not found":
                raise NotFoundException(detail=message)
            raise ClientException(detail=message)
        return AccountPreviewResponse(**preview)

    @post("/portfolios/{portfolio_id:str}/attach")
    async def attach(
        self,
        portfolio_id: str,
        data: dict,
        trading_service: TradingService,
        bond_service: BondService,
        settings: Settings,
    ) -> PortfolioResponse:
        from litestar.exceptions import ClientException, NotFoundException

        from bond_monitor.domain.portfolio.models import AccountKind

        universe = bond_service.load_universe().bonds
        try:
            portfolio = await trading_service.attach_account(
                portfolio_id,
                account_id=str(data["account_id"]),
                kind=AccountKind(str(data.get("kind", "sandbox"))),
                universe=universe,
                key_rate=settings.key_rate,
                tax_rate=settings.tax_rate / 100.0,
                today=date.today(),
            )
        except ValueError as exc:
            message = str(exc)
            if message == "Portfolio not found":
                raise NotFoundException(detail=message)
            raise ClientException(detail=message)
        return portfolio_to_response(portfolio)

    @post("/portfolios/{portfolio_id:str}/detach")
    async def detach(self, portfolio_id: str, trading_service: TradingService) -> PortfolioResponse:
        portfolio = await trading_service.detach_account(portfolio_id)
        return portfolio_to_response(portfolio)

    @post("/portfolios/{portfolio_id:str}/sandbox-pay-in", status_code=HTTP_201_CREATED)
    async def sandbox_pay_in(
        self,
        portfolio_id: str,
        data: SandboxPayInRequest,
        trading_service: TradingService,
    ) -> SandboxPayInResponse:
        from litestar.exceptions import ClientException, NotFoundException

        try:
            result = await trading_service.sandbox_pay_in_for_portfolio(
                portfolio_id,
                amount_rub=data.amount_rub,
            )
        except ValueError as exc:
            message = str(exc)
            if message == "Portfolio not found":
                raise NotFoundException(detail=message)
            raise ClientException(detail=message)
        return SandboxPayInResponse(**result)

    @post("/portfolios/{portfolio_id:str}/sync")
    async def sync_portfolio(
        self,
        portfolio_id: str,
        trading_service: TradingService,
        bond_service: BondService,
        settings: Settings,
    ) -> TradingSyncResponse:
        from litestar.exceptions import ClientException, NotFoundException

        universe = bond_service.load_universe().bonds
        try:
            result = await trading_service.sync_portfolio(
                portfolio_id,
                universe,
                key_rate=settings.key_rate,
                tax_rate=settings.tax_rate / 100.0,
                today=date.today(),
            )
        except ValueError as exc:
            message = str(exc)
            if message == "Portfolio not found":
                raise NotFoundException(detail=message)
            raise ClientException(detail=message)
        return TradingSyncResponse(**result.__dict__)

    @get("/portfolios/{portfolio_id:str}/pending-operations")
    async def pending_ops(
        self,
        portfolio_id: str,
        trading_service: TradingService,
        bond_service: BondService,
        settings: Settings,
    ) -> list[dict]:
        universe = bond_service.load_universe().bonds
        return await trading_service.get_pending_operations(
            portfolio_id,
            universe,
            key_rate=settings.key_rate,
            tax_rate=settings.tax_rate / 100.0,
            today=date.today(),
        )

    @post("/portfolios/{portfolio_id:str}/pending-operations/{op_id:str}/confirm")
    async def confirm_pending(
        self,
        portfolio_id: str,
        op_id: str,
        data: ConfirmPendingRequest,
        trading_service: TradingService,
        bond_service: BondService,
        settings: Settings,
    ) -> TradingSyncResponse:
        from litestar.exceptions import ClientException, NotFoundException

        universe = bond_service.load_universe().bonds
        try:
            result = await trading_service.confirm_pending_operation(
                portfolio_id,
                op_id,
                universe,
                key_rate=settings.key_rate,
                tax_rate=settings.tax_rate / 100.0,
                today=date.today(),
                lots=data.lots,
                price_pct=data.price_pct,
            )
        except ValueError as exc:
            message = str(exc)
            if message == "Portfolio not found":
                raise NotFoundException(detail=message)
            raise ClientException(detail=message)
        return TradingSyncResponse(**result.__dict__)

    @post(
        "/portfolios/{portfolio_id:str}/pending-operations/{op_id:str}/preview",
        status_code=HTTP_200_OK,
    )
    async def preview_pending(
        self,
        portfolio_id: str,
        op_id: str,
        data: ConfirmPendingRequest,
        trading_service: TradingService,
        bond_service: BondService,
        settings: Settings,
    ) -> OrderPreviewResponse:
        from litestar.exceptions import ClientException, NotFoundException

        universe = bond_service.load_universe().bonds
        try:
            result = await trading_service.preview_pending_operation(
                portfolio_id,
                op_id,
                universe,
                key_rate=settings.key_rate,
                tax_rate=settings.tax_rate / 100.0,
                today=date.today(),
                lots=data.lots,
                price_pct=data.price_pct,
            )
        except ValueError as exc:
            message = str(exc)
            if message == "Portfolio not found":
                raise NotFoundException(detail=message)
            raise ClientException(detail=message)
        return OrderPreviewResponse(**result.__dict__)

    @post("/portfolios/{portfolio_id:str}/pending-operations/{op_id:str}/cancel-order")
    async def cancel_pending_order(
        self,
        portfolio_id: str,
        op_id: str,
        trading_service: TradingService,
        bond_service: BondService,
        settings: Settings,
    ) -> TradingSyncResponse:
        from litestar.exceptions import ClientException, NotFoundException

        universe = bond_service.load_universe().bonds
        try:
            result = await trading_service.cancel_pending_order(
                portfolio_id,
                op_id,
                universe,
                key_rate=settings.key_rate,
                tax_rate=settings.tax_rate / 100.0,
                today=date.today(),
            )
        except ValueError as exc:
            message = str(exc)
            if message == "Portfolio not found":
                raise NotFoundException(detail=message)
            raise ClientException(detail=message)
        return TradingSyncResponse(**result.__dict__)

    @post("/portfolios/{portfolio_id:str}/top-up-batches/{batch_id:str}/cancel")
    async def cancel_top_up_batch(
        self,
        portfolio_id: str,
        batch_id: str,
        trading_service: TradingService,
        bond_service: BondService,
        settings: Settings,
    ) -> TradingSyncResponse:
        from litestar.exceptions import ClientException, NotFoundException

        universe = bond_service.load_universe().bonds
        try:
            result = await trading_service.cancel_top_up_batch_operation(
                portfolio_id,
                batch_id,
                universe,
                key_rate=settings.key_rate,
                tax_rate=settings.tax_rate / 100.0,
                today=date.today(),
            )
        except ValueError as exc:
            message = str(exc)
            if message == "Portfolio not found":
                raise NotFoundException(detail=message)
            raise ClientException(detail=message)
        return TradingSyncResponse(**result.__dict__)

    @post("/portfolios/{portfolio_id:str}/positions/{isin:str}/put-offer-decision")
    async def put_offer_decision(
        self,
        portfolio_id: str,
        isin: str,
        data: PutOfferDecisionRequest,
        trading_service: TradingService,
        bond_service: BondService,
        settings: Settings,
    ) -> TradingSyncResponse:
        from litestar.exceptions import ClientException, NotFoundException

        from bond_monitor.domain.portfolio.models import PutOfferDecision

        decision = (
            PutOfferDecision.EXERCISE if data.decision == "exercise" else PutOfferDecision.HOLD
        )
        universe = bond_service.load_universe().bonds
        try:
            result = await trading_service.set_put_offer_decision(
                portfolio_id,
                isin,
                decision,
                universe,
                key_rate=settings.key_rate,
                tax_rate=settings.tax_rate / 100.0,
                today=date.today(),
            )
        except ValueError as exc:
            message = str(exc)
            if message == "Portfolio not found":
                raise NotFoundException(detail=message)
            raise ClientException(detail=message)
        return TradingSyncResponse(**result.__dict__)

    @get("/portfolios/{portfolio_id:str}/performance")
    async def performance(
        self,
        portfolio_id: str,
        trading_service: TradingService,
    ) -> dict | None:
        return await trading_service.get_performance(portfolio_id)

    @get("/portfolios/{portfolio_id:str}/account-operations")
    async def account_operations(
        self,
        portfolio_id: str,
        trading_service: TradingService,
        bond_service: BondService,
    ) -> AccountOperationsResponse:
        from litestar.exceptions import ClientException, NotFoundException

        universe = bond_service.load_universe().bonds
        try:
            operations = await trading_service.get_account_operations_history(portfolio_id)
        except ValueError as exc:
            message = str(exc)
            if message == "Portfolio not found":
                raise NotFoundException(detail=message)
            raise ClientException(detail=message)
        bonds_by_figi = {bond.figi: bond for bond in universe if bond.figi}
        return AccountOperationsResponse(
            operations=[
                account_operation_to_response(op, bonds_by_figi=bonds_by_figi) for op in operations
            ]
        )
