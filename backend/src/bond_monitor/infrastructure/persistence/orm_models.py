"""SQLAlchemy ORM models."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from bond_monitor.infrastructure.persistence.database import Base


class PortfolioRow(Base):
    """Portfolio aggregate root stored as structured JSON + scalar fields."""

    __tablename__ = "portfolios"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    initial_amount_rub: Mapped[float] = mapped_column(Float, nullable=False)
    horizon_date: Mapped[date] = mapped_column(Date, nullable=False)
    risk_profile: Mapped[str] = mapped_column(String(32), nullable=False)
    cash_balance_rub: Mapped[float] = mapped_column(Float, default=0.0)
    mode: Mapped[str] = mapped_column(String(32), default="simulation")
    account_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    account_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class FavoriteRow(Base):
    """User favorite bond ISIN."""

    __tablename__ = "favorites"

    isin: Mapped[str] = mapped_column(String(16), primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AppSettingRow(Base):
    """Key-value application settings (overrides env defaults)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


class UserNotificationRow(Base):
    """In-app notification read-model."""

    __tablename__ = "user_notifications"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    portfolio_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    urgency: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DeploySessionRow(Base):
    """Ephemeral frozen deploy plan for atomic buy/reinvest execution."""

    __tablename__ = "deploy_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    cash_snapshot_rub: Mapped[float] = mapped_column(Float, nullable=False)
    items_json: Mapped[list] = mapped_column(JSON, nullable=False)
    warnings_json: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
