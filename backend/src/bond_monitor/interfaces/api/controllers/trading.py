"""Trading mode API controllers."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date

from litestar import Controller, delete, get, post
from litestar.di import Provide
from litestar.exceptions import ClientException, NotFoundException
from litestar.status_codes import HTTP_200_OK, HTTP_201_CREATED, HTTP_204_NO_CONTENT

from bond_monitor.application.bonds.bond_service import BondService
from bond_monitor.application.portfolio.portfolio_service import PortfolioService
from bond_monitor.application.trading.trading_service import TradingService
from bond_monitor.application.trading.deploy_session_use_case import (
    DeploySessionConflictError,
    DeploySessionEmptyError,
    DeploySessionNotFoundError,
)
from bond_monitor.application.trading.deploy_session_mapper import deploy_session_to_response
from bond_monitor.application.trading.types import TradingAdviceResult
from bond_monitor.domain.portfolio.policies import duration_policy_for_portfolio
from bond_monitor.domain.trading.models import AccountKind
from bond_monitor.interfaces.api.controllers.bonds import provide_bond_service
from bond_monitor.interfaces.api.duration_params import parse_rate_scenario
from bond_monitor.interfaces.api.providers import (
    provide_portfolio_service,
    provide_trading_service,
)
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
    DeploySessionResponse,
    DeploySessionProgressResponse,
    DeploySessionItemResponse,
    PerformanceDataResponse,
    HoldingResponse,
    SuggestionResponse,
    ActiveOrderResponse,
    TradingStateResponse,
)
from bond_monitor.interfaces.schemas.serializers import (
    account_operation_to_response,
    plan_to_response,
    portfolio_to_response,
)


def advice_to_response(result: TradingAdviceResult) -> TradingAdviceResponse:
    performance = None
    if result.performance is not None:
        performance = PerformanceDataResponse(**asdict(result.performance))
    deploy_session = None
    if result.deploy_session is not None:
        ds = result.deploy_session
        deploy_session = DeploySessionResponse(
            id=ds.id,
            status=ds.status,
            expires_at=ds.expires_at,
            cash_snapshot_rub=ds.cash_snapshot_rub,
            progress=DeploySessionProgressResponse(**asdict(ds.progress)),
            items=[DeploySessionItemResponse(**asdict(item)) for item in ds.items],
            warnings=ds.warnings,
        )
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
        weighted_duration_years=result.weighted_duration_years,
        deploy_session=deploy_session,
    )


def deploy_session_api_response(session) -> DeploySessionResponse:
    mapped = deploy_session_to_response(session)
    return DeploySessionResponse(
        id=mapped.id,
        status=mapped.status,
        expires_at=mapped.expires_at,
        cash_snapshot_rub=mapped.cash_snapshot_rub,
        progress=DeploySessionProgressResponse(**asdict(mapped.progress)),
        items=[DeploySessionItemResponse(**asdict(item)) for item in mapped.items],
        warnings=mapped.warnings,
    )


class TradingController(Controller):
    path = "/api/v1"
    dependencies = {
        "trading_service": Provide(provide_trading_service),
        "bond_service": Provide(provide_bond_service),
        "portfolio_service": Provide(provide_portfolio_service),
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
        portfolio_service: PortfolioService,
        bond_service: BondService,
        settings: Settings,
        rate_scenario: str | None = None,
    ) -> TradingAdviceResponse:
        portfolio = await portfolio_service.get_portfolio(portfolio_id)
        if portfolio is None:
            raise NotFoundException(detail="Portfolio not found")
        duration_policy = duration_policy_for_portfolio(
            portfolio,
            rate_scenario=parse_rate_scenario(rate_scenario),
        )
        universe = bond_service.load_universe().bonds
        try:
            result = await trading_service.get_advice(
                portfolio_id,
                universe,
                key_rate=settings.key_rate,
                tax_rate=settings.tax_rate_fraction,
                today=date.today(),
                duration_policy=duration_policy,
            )
        except ValueError as exc:
            message = str(exc)
            if message == "Portfolio not found":
                raise NotFoundException(detail=message)
            raise ClientException(detail=message)
        return advice_to_response(result)

    @get("/portfolios/{portfolio_id:str}/trading-state")
    async def get_trading_state(
        self,
        portfolio_id: str,
        trading_service: TradingService,
        portfolio_service: PortfolioService,
        bond_service: BondService,
        settings: Settings,
        rate_scenario: str | None = None,
    ) -> TradingStateResponse:
        portfolio = await portfolio_service.get_portfolio(portfolio_id)
        if portfolio is None:
            raise NotFoundException(detail="Portfolio not found")
        duration_policy = duration_policy_for_portfolio(
            portfolio,
            rate_scenario=parse_rate_scenario(rate_scenario),
        )
        universe = bond_service.load_universe().bonds
        try:
            result = await trading_service.get_trading_state(
                portfolio_id,
                universe,
                key_rate=settings.key_rate,
                tax_rate=settings.tax_rate_fraction,
                today=date.today(),
                duration_policy=duration_policy,
            )
        except ValueError as exc:
            message = str(exc)
            if message == "Portfolio not found":
                raise NotFoundException(detail=message)
            raise ClientException(detail=message)
        return TradingStateResponse(
            plan=plan_to_response(result.plan),
            advice=advice_to_response(result.advice),
        )

    @post("/portfolios/{portfolio_id:str}/deploy-sessions", status_code=HTTP_201_CREATED)
    async def create_deploy_session(
        self,
        portfolio_id: str,
        trading_service: TradingService,
        bond_service: BondService,
        settings: Settings,
    ) -> DeploySessionResponse:
        universe = bond_service.load_universe().bonds
        try:
            session = await trading_service.create_deploy_session(
                portfolio_id,
                universe,
                key_rate=settings.key_rate,
                tax_rate=settings.tax_rate_fraction,
                today=date.today(),
            )
        except DeploySessionConflictError as exc:
            raise ClientException(detail=str(exc), status_code=409) from exc
        except DeploySessionEmptyError as exc:
            raise ClientException(detail=str(exc), status_code=422) from exc
        except ValueError as exc:
            message = str(exc)
            if message == "Portfolio not found":
                raise NotFoundException(detail=message)
            raise ClientException(detail=message)
        return deploy_session_api_response(session)

    @get("/portfolios/{portfolio_id:str}/deploy-sessions/active")
    async def get_active_deploy_session(
        self,
        portfolio_id: str,
        trading_service: TradingService,
    ) -> DeploySessionResponse:
        try:
            session = await trading_service.get_active_deploy_session(portfolio_id)
        except ValueError as exc:
            message = str(exc)
            if message == "Portfolio not found":
                raise NotFoundException(detail=message)
            raise ClientException(detail=message)
        if session is None:
            raise NotFoundException(detail="Active deploy session not found")
        return deploy_session_api_response(session)

    @post("/portfolios/{portfolio_id:str}/deploy-sessions/{session_id:str}/refresh")
    async def refresh_deploy_session(
        self,
        portfolio_id: str,
        session_id: str,
        trading_service: TradingService,
        bond_service: BondService,
        settings: Settings,
    ) -> DeploySessionResponse:
        universe = bond_service.load_universe().bonds
        try:
            session = await trading_service.refresh_deploy_session(
                portfolio_id,
                session_id,
                universe,
                key_rate=settings.key_rate,
                tax_rate=settings.tax_rate_fraction,
                today=date.today(),
            )
        except DeploySessionNotFoundError as exc:
            raise NotFoundException(detail=str(exc)) from exc
        except DeploySessionEmptyError as exc:
            raise ClientException(detail=str(exc), status_code=422) from exc
        except ValueError as exc:
            message = str(exc)
            if message == "Portfolio not found":
                raise NotFoundException(detail=message)
            raise ClientException(detail=message)
        return deploy_session_api_response(session)

    @delete(
        "/portfolios/{portfolio_id:str}/deploy-sessions/{session_id:str}",
        status_code=HTTP_200_OK,
    )
    async def cancel_deploy_session(
        self,
        portfolio_id: str,
        session_id: str,
        trading_service: TradingService,
    ) -> DeploySessionResponse:
        try:
            session = await trading_service.cancel_deploy_session(portfolio_id, session_id)
        except DeploySessionNotFoundError as exc:
            raise NotFoundException(detail=str(exc)) from exc
        except ValueError as exc:
            message = str(exc)
            if message == "Portfolio not found":
                raise NotFoundException(detail=message)
            raise ClientException(detail=message)
        return deploy_session_api_response(session)

    @post(
        "/portfolios/{portfolio_id:str}/deploy-sessions/{session_id:str}/items/{item_id:str}/skip",
        status_code=HTTP_200_OK,
    )
    async def skip_deploy_session_item(
        self,
        portfolio_id: str,
        session_id: str,
        item_id: str,
        trading_service: TradingService,
    ) -> DeploySessionResponse:
        try:
            session = await trading_service.skip_deploy_session_item(
                portfolio_id,
                session_id,
                item_id,
            )
        except DeploySessionNotFoundError as exc:
            raise NotFoundException(detail=str(exc)) from exc
        except ValueError as exc:
            message = str(exc)
            if message == "Portfolio not found":
                raise NotFoundException(detail=message)
            raise ClientException(detail=message)
        return deploy_session_api_response(session)

    @post(
        "/portfolios/{portfolio_id:str}/risk-alerts/{isin:str}/acknowledge",
        status_code=HTTP_204_NO_CONTENT,
    )
    async def acknowledge_risk_alert(
        self,
        portfolio_id: str,
        isin: str,
        trading_service: TradingService,
        bond_service: BondService,
    ) -> None:
        universe = bond_service.load_universe().bonds
        try:
            await trading_service.acknowledge_risk_alert(portfolio_id, isin, universe)
        except ValueError as exc:
            message = str(exc)
            if message == "Portfolio not found":
                raise NotFoundException(detail=message)
            raise ClientException(detail=message)

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
