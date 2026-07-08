"""API controllers package."""

from bond_monitor.interfaces.api.controllers.auth import AuthController
from bond_monitor.interfaces.api.controllers.bonds import (
    BondsController,
    FavoritesController,
    RatingsController,
    provide_bond_service,
    provide_favorites_repo,
)
from bond_monitor.interfaces.api.controllers.portfolio import (
    CalculatorController,
    ConfigController,
    HealthController,
    PortfoliosController,
    provide_portfolio_service,
)
from bond_monitor.interfaces.api.controllers.trading import TradingController, provide_trading_service

__all__ = [
    "AuthController",
    "BondsController",
    "CalculatorController",
    "ConfigController",
    "FavoritesController",
    "HealthController",
    "PortfoliosController",
    "RatingsController",
    "TradingController",
    "provide_bond_service",
    "provide_favorites_repo",
    "provide_portfolio_service",
    "provide_trading_service",
]
