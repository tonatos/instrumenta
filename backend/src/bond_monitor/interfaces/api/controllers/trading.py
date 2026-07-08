"""Trading mode API controllers."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date

from litestar import Controller, delete, get, post
from litestar.di import Provide
from litestar.exceptions import ClientException, NotFoundException
from litestar.status_codes import HTTP_200_OK, HTTP_201_CREATED
from sqlalchemy.ext.asyncio import AsyncSession

from bond_monitor.application.bonds.bond_service import BondService
from bond_monitor.application.trading.trading_service import TradingService
from bond_monitor.application.trading.types import TradingAdviceResult
from bond_monitor.domain.trading.models import AccountKind
from bond_monitor.infrastructure.persistence.repository import PortfolioRepository
from bond_monitor.interfaces.api.controllers.bonds import provide_bond_service
from bond_monitor.interfaces.config import Settings
from bond_monitor.interfaces.schemas.api import (
    AccountOperationsResponse,
    AccountPreviewResponse,
    BrokerAccountResponse,
    ClearAccountRequest,
    CreateSandboxAccountRequest,
    DeleteSandboxAccountResponse,
    OrderPreviewResponse,
    PlaceOrderRequest,
    PlaceOrderResponse,
    PortfolioResponse,
    SandboxPayInRequest,
    SandboxPayInResponse,
    SellPositionPreviewResponse,
    SellPositionRequest,
    SellQuoteResponse,
    TradingAdviceResponse,
    PerformanceDataResponse,
    HoldingResponse,
    SuggestionResponse,
    ActiveOrderResponse,
)
from bond_monitor.interfaces.schemas.serializers import (
    account_operation_to_response,
    portfolio_to_response,
)


async def provide_trading_service(
    db_session: AsyncSession,
    settings: Settings,
) -> TradingService:
    return TradingService(
        PortfolioRepository(db_session),
        sandbox_token=settings.t_trading_token_sandbox,
        production_token=settings.t_trading_token_production,
    )


def advice_to_response(result: TradingAdviceResult) -> TradingAdviceResponse:
    performance = None
    if result.performance is not None:
        performance = PerformanceDataResponse(**asdict(result.performance))
    return TradingAdviceResponse(
        holdings=[HoldingResponse(**asdict(h)) for h in result.holdings],
        cashflow=result.cashflow,
        performance=performance,
        suggestions=[SuggestionResponse(**asdict(s)) for s in result.suggestions],
        active_orders=[ActiveOrderResponse(**asdict(o)) for o in result.active_orders],
        money_rub=result.money_rub,
        available_money_rub=result.available_money_rub,
        blocked_money_rub=result.blocked_money_rub,
        warnings=result.warnings,
        as_of=result.as_of,
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
        return await trading_service.list_accounts(AccountKind(kind))

    @post("/accounts/sandbox", status_code=HTTP_201_CREATED)
    async def create_sandbox_account(
        self,
        data: CreateSandboxAccountRequest,
        trading_service: TradingService,
    ) -> BrokerAccountResponse:
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
        bond_service: BondService,
        account_id: str,
        kind: str = "sandbox",
    ) -> AccountPreviewResponse:
        universe = bond_service.load_universe().bonds
        try:
            preview = await trading_service.get_account_preview(
                portfolio_id,
                account_id=account_id,
                kind=AccountKind(kind),
                universe=universe,
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
        bond_service: BondService,
    ) -> AccountPreviewResponse:
        universe = bond_service.load_universe().bonds
        try:
            preview = await trading_service.clear_account_for_attach(
                portfolio_id,
                account_id=data.account_id,
                kind=AccountKind(data.kind),
                pay_in_rub=data.pay_in_rub,
                universe=universe,
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
        universe = bond_service.load_universe().bonds
        try:
            portfolio = await trading_service.attach_account(
                portfolio_id,
                account_id=str(data["account_id"]),
                kind=AccountKind(str(data.get("kind", "sandbox"))),
                universe=universe,
                key_rate=settings.key_rate,
                tax_rate=settings.tax_rate_fraction,
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

    @get("/portfolios/{portfolio_id:str}/advice")
    async def get_advice(
        self,
        portfolio_id: str,
        trading_service: TradingService,
        bond_service: BondService,
        settings: Settings,
    ) -> TradingAdviceResponse:
        universe = bond_service.load_universe().bonds
        try:
            result = await trading_service.get_advice(
                portfolio_id,
                universe,
                key_rate=settings.key_rate,
                tax_rate=settings.tax_rate_fraction,
                today=date.today(),
            )
        except ValueError as exc:
            message = str(exc)
            if message == "Portfolio not found":
                raise NotFoundException(detail=message)
            raise ClientException(detail=message)
        return advice_to_response(result)

    @post(
        "/portfolios/{portfolio_id:str}/orders/preview",
        status_code=HTTP_200_OK,
    )
    async def preview_order(
        self,
        portfolio_id: str,
        data: PlaceOrderRequest,
        trading_service: TradingService,
        bond_service: BondService,
    ) -> OrderPreviewResponse:
        universe = bond_service.load_universe().bonds
        try:
            result = await trading_service.preview_order(
                portfolio_id,
                universe,
                isin=data.isin,
                direction=data.direction,
                lots=data.lots,
                price_pct=data.price_pct,
                figi=data.figi,
            )
        except ValueError as exc:
            message = str(exc)
            if message == "Portfolio not found":
                raise NotFoundException(detail=message)
            raise ClientException(detail=message)
        return OrderPreviewResponse(**result.__dict__)

    @post("/portfolios/{portfolio_id:str}/orders/place", status_code=HTTP_201_CREATED)
    async def place_order(
        self,
        portfolio_id: str,
        data: PlaceOrderRequest,
        trading_service: TradingService,
        bond_service: BondService,
    ) -> PlaceOrderResponse:
        universe = bond_service.load_universe().bonds
        try:
            result = await trading_service.place_order(
                portfolio_id,
                universe,
                isin=data.isin,
                direction=data.direction,
                lots=data.lots,
                price_pct=data.price_pct,
                figi=data.figi,
                suggestion_id=data.suggestion_id,
            )
        except ValueError as exc:
            message = str(exc)
            if message == "Portfolio not found":
                raise NotFoundException(detail=message)
            raise ClientException(detail=message)
        return PlaceOrderResponse(**result.__dict__)

    @post("/portfolios/{portfolio_id:str}/orders/{order_id:str}/cancel")
    async def cancel_order(
        self,
        portfolio_id: str,
        order_id: str,
        trading_service: TradingService,
    ) -> dict:
        try:
            await trading_service.cancel_order(portfolio_id, order_id)
        except ValueError as exc:
            message = str(exc)
            if message == "Portfolio not found":
                raise NotFoundException(detail=message)
            raise ClientException(detail=message)
        return {"order_id": order_id, "status": "cancelled"}

    @post(
        "/portfolios/{portfolio_id:str}/positions/{isin:str}/sell-preview",
        status_code=HTTP_200_OK,
    )
    async def sell_position_preview(
        self,
        portfolio_id: str,
        isin: str,
        data: SellPositionRequest,
        trading_service: TradingService,
        bond_service: BondService,
    ) -> SellPositionPreviewResponse:
        universe = bond_service.load_universe().bonds
        try:
            result = await trading_service.preview_sell_position(
                portfolio_id,
                isin,
                universe,
                lots=data.lots,
                price_pct=data.price_pct,
                today=date.today(),
            )
        except ValueError as exc:
            message = str(exc)
            if message == "Portfolio not found":
                raise NotFoundException(detail=message)
            raise ClientException(detail=message)
        return SellPositionPreviewResponse(**result.__dict__)

    @get("/portfolios/{portfolio_id:str}/positions/{isin:str}/sell-quote")
    async def sell_quote(
        self,
        portfolio_id: str,
        isin: str,
        trading_service: TradingService,
        bond_service: BondService,
    ) -> SellQuoteResponse:
        universe = bond_service.load_universe().bonds
        try:
            result = await trading_service.get_sell_quote(portfolio_id, isin, universe)
        except ValueError as exc:
            message = str(exc)
            if message == "Portfolio not found":
                raise NotFoundException(detail=message)
            raise ClientException(detail=message)
        return SellQuoteResponse(**result.__dict__)

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
