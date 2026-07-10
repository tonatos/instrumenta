"""Dev CLI for local notification testing."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date

from bond_monitor.application.bonds.bond_service import BondService
from bond_monitor.application.bonds.bond_service import BondService
from bond_monitor.application.trading.context import TradingContext
from bond_monitor.dev.overrides import (
    build_put_offer_overrides,
    build_risk_default_overrides,
    build_risk_downgrade_overrides,
    get_dev_overrides_path,
    notifications_dev_enabled,
    save_dev_overrides,
)
from bond_monitor.domain.trading.advisory import holding_isins_from_snapshot
from bond_monitor.infrastructure.notifications.ledger_repository import LedgerRepository
from bond_monitor.infrastructure.persistence.database import get_session_factory, init_db
from bond_monitor.infrastructure.persistence.repository import PortfolioRepository
from bond_monitor.infrastructure.tinvest.snapshot_adapter import broker_snapshot_from_infrastructure
from bond_monitor.interfaces.config import get_settings
from bond_monitor.interfaces.logging_config import configure_logging
from bond_monitor.notifier.__main__ import _run_scan
from bond_monitor.application.trading import broker

logger = logging.getLogger(__name__)

_SIMULATE_SCENARIOS = {
    "put-offer": build_put_offer_overrides,
    "risk-default": build_risk_default_overrides,
    "risk-downgrade": build_risk_downgrade_overrides,
}


async def _resolve_holding_isin(
    trading_ctx: TradingContext,
    bond_service: BondService,
    portfolio_id: str,
    *,
    isin: str | None,
) -> str:
    portfolio = await trading_ctx.get_trading_portfolio(portfolio_id)
    token = trading_ctx.token(portfolio.account_kind)  # type: ignore[arg-type]
    snapshot = broker.get_account_snapshot(
        token,
        portfolio.account_kind,  # type: ignore[arg-type]
        portfolio.account_id,  # type: ignore[arg-type]
    )
    broker_snapshot = broker_snapshot_from_infrastructure(snapshot)
    bond_lots = sum(1 for pos in broker_snapshot.bond_positions.values() if pos.lots > 0)
    if bond_lots == 0:
        raise ValueError(
            f"Portfolio {portfolio_id} has no holdings on the broker account. "
            "Buy a bond in sandbox first."
        )

    universe_lookup = bond_service.load_universe().bonds
    holding_isins = sorted(holding_isins_from_snapshot(broker_snapshot, universe_lookup))
    if not holding_isins:
        figis = [
            figi
            for figi, pos in broker_snapshot.bond_positions.items()
            if pos.lots > 0
        ]
        raise ValueError(
            f"Portfolio {portfolio_id} has {bond_lots} bond position(s) on the account "
            f"(FIGIs: {', '.join(figis)}), but ISIN mapping failed. "
            "Check TINKOFF_TOKEN and bond universe cache."
        )
    if isin:
        if isin not in holding_isins:
            raise ValueError(
                f"ISIN {isin} is not held on account. Holdings: {', '.join(holding_isins)}"
            )
        return isin
    return holding_isins[0]


async def _cmd_simulate(args: argparse.Namespace) -> int:
    if not notifications_dev_enabled():
        print(
            "NOTIFICATIONS_DEV is disabled. Set NOTIFICATIONS_DEV=true in .env.",
            file=sys.stderr,
        )
        return 1

    builder = _SIMULATE_SCENARIOS.get(args.scenario)
    if builder is None:
        print(f"Unknown scenario: {args.scenario}", file=sys.stderr)
        return 1

    await init_db()
    session_factory = get_session_factory()
    settings = get_settings()
    bond_service = BondService(
        key_rate=settings.key_rate,
        tax_rate=settings.tax_rate,
        tinkoff_token=settings.tinkoff_token,
        max_days=settings.max_days,
        min_volume_rub=settings.min_volume_rub,
    )
    async with session_factory() as session:
        repo = PortfolioRepository(session)
        trading_ctx = TradingContext(
            repo,
            sandbox_token=settings.t_trading_token_sandbox,
            production_token=settings.t_trading_token_production,
        )
        resolved_isin = await _resolve_holding_isin(
            trading_ctx,
            bond_service,
            args.portfolio,
            isin=args.isin,
        )

    if args.scenario == "put-offer":
        payload = builder(portfolio_id=args.portfolio, isin=resolved_isin, today=date.today())
    else:
        payload = builder(portfolio_id=args.portfolio, isin=resolved_isin)

    overrides_path = get_dev_overrides_path()
    save_dev_overrides(overrides_path, payload)
    print(f"Wrote {args.scenario} overrides for {resolved_isin} → {overrides_path}")
    return 0


async def _cmd_scan(_args: argparse.Namespace) -> int:
    if not notifications_dev_enabled():
        print(
            "NOTIFICATIONS_DEV is disabled. Set NOTIFICATIONS_DEV=true in .env.",
            file=sys.stderr,
        )
        return 1

    settings = get_settings()
    configure_logging(settings.log_level)
    await init_db()

    from bond_monitor.infrastructure.notifications.redis_bus import NotificationBus
    from bond_monitor.infrastructure.notifications.telegram_client import TelegramNotifier
    from bond_monitor.notifier.settings import get_notifier_settings

    notifier_settings = get_notifier_settings()
    session_factory = get_session_factory()
    trading_ctx = TradingContext(
        PortfolioRepository(session_factory()),
        sandbox_token=settings.t_trading_token_sandbox,
        production_token=settings.t_trading_token_production,
    )
    bond_service = BondService(
        key_rate=settings.key_rate,
        tax_rate=settings.tax_rate,
        tinkoff_token=settings.tinkoff_token,
        max_days=settings.max_days,
        min_volume_rub=settings.min_volume_rub,
    )
    ledger = LedgerRepository(notifier_settings.notifier_ledger_path)
    bus: NotificationBus | None = None
    try:
        bus = NotificationBus(notifier_settings.redis_url)
        bus.ping()
    except Exception:
        logger.warning("Redis unavailable, falling back to direct DB writes", exc_info=True)

    telegram = TelegramNotifier(
        notifier_settings.telegram_bot_token,
        notifier_settings.telegram_notify_user_id,
    )
    count = await _run_scan(
        trading_ctx=trading_ctx,
        bond_service=bond_service,
        ledger=ledger,
        bus=bus,
        telegram=telegram,
        session_factory=session_factory,
    )
    print(f"Scan complete, alerts processed={count}")
    return 0


async def _cmd_reset(args: argparse.Namespace) -> int:
    settings = get_settings()
    ledger = LedgerRepository(settings.notifier_ledger_path)
    if args.portfolio:
        deleted = ledger.delete_for_portfolio(args.portfolio)
        print(f"Deleted {deleted} ledger entries for portfolio {args.portfolio}")
    else:
        deleted = ledger.delete_all()
        print(f"Deleted {deleted} ledger entries")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bond_monitor.dev.notifications",
        description="Local dev tools for notification testing",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    simulate = sub.add_parser("simulate", help="Write dev overrides for a scenario")
    simulate.add_argument(
        "scenario",
        choices=sorted(_SIMULATE_SCENARIOS),
        help="Alert scenario to simulate",
    )
    simulate.add_argument("--portfolio", required=True, help="Trading portfolio ID")
    simulate.add_argument("--isin", help="Held ISIN (default: first holding)")

    sub.add_parser("scan", help="Run one notifier scan cycle")

    reset = sub.add_parser("reset", help="Clear notifier delivery ledger")
    reset.add_argument("--portfolio", help="Limit reset to one portfolio")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "simulate":
        return asyncio.run(_cmd_simulate(args))
    if args.command == "scan":
        return asyncio.run(_cmd_scan(args))
    if args.command == "reset":
        return asyncio.run(_cmd_reset(args))
    parser.error(f"Unknown command: {args.command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
