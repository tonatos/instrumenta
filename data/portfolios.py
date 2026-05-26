"""
Persistent storage for user portfolios.

Хранит список портфелей в ``$CACHE_DIR/portfolios.json`` (по умолчанию
``<repo>/cache/portfolios.json``). В Docker этот путь смонтирован
read-write, так что данные переживают рестарт контейнера.

Формат файла::

    {
      "_updated_at": "2026-05-26T00:30:00+00:00",
      "_count": 2,
      "portfolios": [
        {
          "id": "0e4f…",
          "name": "Краткосрочный",
          "created_at": "...",
          "updated_at": "...",
          "initial_amount_rub": 500000.0,
          "horizon_date": "2027-06-01",
          "risk_profile": "normal",
          "cash_balance_rub": 0.0,
          "positions": [...],
          "slots": [...]
        }
      ]
    }

API изолирован: модуль не знает про ``BondRecord`` / Streamlit / planner —
это чистый слой персистентности списка :class:`core.portfolio_model.Portfolio`.

CRUD-операции (``create_portfolio`` / ``update_portfolio`` / ``delete_portfolio``)
сразу сохраняют файл — это упрощает контракт со стороны UI: после возврата
из функции состояние на диске согласовано с возвращённым объектом.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from core.portfolio_model import Portfolio, RiskProfile

logger = logging.getLogger(__name__)

# Default cache dir mirrors data.favorites / data.ratings_loader so paths are
# consistent across Docker (``/app/cache``) and local dev (``<repo>/cache``).
_DEFAULT_CACHE_DIR: Path = Path(__file__).resolve().parent.parent / "cache"
_CACHE_DIR: Path = Path(os.getenv("CACHE_DIR") or _DEFAULT_CACHE_DIR)
PORTFOLIOS_PATH: Path = _CACHE_DIR / "portfolios.json"


def load_portfolios() -> list[Portfolio]:
    """Загрузить список портфелей из файла. Пустой список при отсутствии."""
    if not PORTFOLIOS_PATH.exists():
        return []
    try:
        with PORTFOLIOS_PATH.open(encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)
    except (json.JSONDecodeError, OSError):
        logger.exception("Failed to load %s", PORTFOLIOS_PATH)
        return []

    raw_portfolios = data.get("portfolios")
    if not isinstance(raw_portfolios, list):
        logger.warning("Portfolios file has unexpected shape at %s", PORTFOLIOS_PATH)
        return []

    portfolios: list[Portfolio] = []
    for raw in raw_portfolios:
        if not isinstance(raw, dict):
            logger.warning("Skipping non-dict portfolio entry: %r", raw)
            continue
        try:
            portfolios.append(Portfolio.from_dict(raw))
        except (KeyError, ValueError, TypeError):
            logger.exception("Failed to parse portfolio %r", raw.get("id"))
            continue
    return portfolios


def save_portfolios(portfolios: list[Portfolio]) -> Path:
    """Атомарно сохранить весь список портфелей в файл.

    Запись идёт во временный ``.tmp``-файл с последующим ``replace`` — это
    защищает от обрезанного JSON при падении процесса в момент сохранения.
    """
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "_updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "_count": len(portfolios),
        "portfolios": [p.to_dict() for p in portfolios],
    }
    tmp_path = PORTFOLIOS_PATH.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp_path.replace(PORTFOLIOS_PATH)
    logger.info("Portfolios saved: %d entries → %s", len(portfolios), PORTFOLIOS_PATH)
    return PORTFOLIOS_PATH


def create_portfolio(
    *,
    name: str,
    initial_amount_rub: float,
    horizon_date: date,
    risk_profile: RiskProfile,
) -> Portfolio:
    """Создать новый портфель и сохранить его в файл.

    Идентификатор портфеля генерируется автоматически (UUID4 hex).
    Возвращает созданный объект — у него уже проставлены ``id`` /
    ``created_at`` / ``updated_at``.
    """
    portfolio = Portfolio(
        name=name.strip() or "Новый портфель",
        initial_amount_rub=float(initial_amount_rub),
        horizon_date=horizon_date,
        risk_profile=risk_profile,
    )
    portfolios = load_portfolios()
    portfolios.append(portfolio)
    save_portfolios(portfolios)
    return portfolio


def update_portfolio(portfolio: Portfolio) -> Portfolio:
    """Заменить портфель с тем же ``id`` на переданный и сохранить.

    Если портфель с таким ``id`` ещё не существует — добавит его (это
    делает функцию идемпотентной для миграционных сценариев).
    """
    portfolio.touch()
    portfolios = load_portfolios()
    replaced = False
    for idx, existing in enumerate(portfolios):
        if existing.id == portfolio.id:
            portfolios[idx] = portfolio
            replaced = True
            break
    if not replaced:
        portfolios.append(portfolio)
    save_portfolios(portfolios)
    return portfolio


def delete_portfolio(portfolio_id: str) -> bool:
    """Удалить портфель по id. Возвращает ``True``, если удалён."""
    if not portfolio_id:
        return False
    portfolios = load_portfolios()
    new_list = [p for p in portfolios if p.id != portfolio_id]
    if len(new_list) == len(portfolios):
        return False
    save_portfolios(new_list)
    return True


def get_portfolio(portfolio_id: str) -> Portfolio | None:
    """Найти портфель по id. ``None``, если не найден."""
    if not portfolio_id:
        return None
    for p in load_portfolios():
        if p.id == portfolio_id:
            return p
    return None


def rename_portfolio(portfolio_id: str, new_name: str) -> Portfolio | None:
    """Переименовать портфель. Возвращает обновлённый объект или ``None``."""
    portfolio = get_portfolio(portfolio_id)
    if portfolio is None:
        return None
    portfolio.name = new_name.strip() or portfolio.name
    return update_portfolio(portfolio)
