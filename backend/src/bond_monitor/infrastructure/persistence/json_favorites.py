"""
Persistent favorites storage.

Хранит список «избранных» облигаций (по ISIN) в JSON-файле
``$CACHE_DIR/favorites.json`` (по умолчанию ``<repo>/cache/favorites.json``).
В Docker этот путь смонтирован read-write — данные переживают рестарт
контейнера.

Формат файла::

    {
      "_updated_at": "2026-05-25T20:00:00+00:00",
      "_count": 3,
      "isins": ["RU000A0JX0J2", "RU000A101NJ6", "RU000A107RM8"]
    }

Содержимое всегда нормализуется в отсортированный список без дубликатов
для стабильных diff-ов.

API изолирован: модуль не знает про ``BondRecord``/Streamlit — это
просто слой персистентности множества ISIN-ов.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default cache dir mirrors data.ratings_loader so paths are consistent
# across Docker (``/app/cache``) and local dev (``<repo>/cache``).
from bond_monitor.infrastructure.paths import get_cache_dir

_CACHE_DIR: Path = get_cache_dir()
FAVORITES_PATH: Path = _CACHE_DIR / "favorites.json"


def load_favorites() -> set[str]:
    """
    Загрузить множество избранных ISIN-ов из файла.

    Возвращает пустое множество, если файл не существует или повреждён.
    """
    if not FAVORITES_PATH.exists():
        return set()
    try:
        with FAVORITES_PATH.open(encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)
    except (json.JSONDecodeError, OSError):
        logger.exception("Failed to load %s", FAVORITES_PATH)
        return set()
    isins = data.get("isins")
    if not isinstance(isins, list):
        logger.warning("Favorites file has unexpected shape at %s", FAVORITES_PATH)
        return set()
    return {str(x) for x in isins if isinstance(x, str) and x}


def save_favorites(isins: set[str]) -> Path:
    """
    Атомарно записать множество избранных ISIN-ов в файл.

    ISIN-ы сортируются, дубли исключаются — diff между версиями
    остаётся минимальным.
    """
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    sorted_isins = sorted(isins)
    payload: dict[str, Any] = {
        "_updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "_count": len(sorted_isins),
        "isins": sorted_isins,
    }
    tmp_path = FAVORITES_PATH.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp_path.replace(FAVORITES_PATH)
    logger.info("Favorites saved: %d entries → %s", len(sorted_isins), FAVORITES_PATH)
    return FAVORITES_PATH


def toggle_favorite(isin: str) -> bool:
    """
    Переключить состояние «в избранном» для ISIN.

    Возвращает новое состояние: ``True`` — в избранном после операции,
    ``False`` — удалено.
    """
    if not isin:
        return False
    favorites = load_favorites()
    if isin in favorites:
        favorites.discard(isin)
        new_state = False
    else:
        favorites.add(isin)
        new_state = True
    save_favorites(favorites)
    return new_state


def add_favorite(isin: str) -> None:
    """Добавить ISIN в избранное (идемпотентно)."""
    if not isin:
        return
    favorites = load_favorites()
    if isin in favorites:
        return
    favorites.add(isin)
    save_favorites(favorites)


def remove_favorite(isin: str) -> None:
    """Удалить ISIN из избранного (идемпотентно)."""
    if not isin:
        return
    favorites = load_favorites()
    if isin not in favorites:
        return
    favorites.discard(isin)
    save_favorites(favorites)


def sync_visible_favorites(
    visible_isins: set[str],
    new_visible_favs: set[str],
) -> bool:
    """
    Синхронизировать favorites только по «видимому» подмножеству ISIN-ов.

    Используется обработчиком ``st.data_editor`` в скринере: после клика
    по чекбоксу мы знаем актуальное состояние избранного для бумаг,
    которые сейчас отображены в таблице (``visible_isins``). Но в файле
    favorites могут лежать ISIN-ы, не попавшие под текущие фильтры
    окна / боковые фильтры — их **трогать нельзя**, иначе при
    переключении одного чекбокса мы случайно «сотрём» все избранные
    бумаги, которых сейчас просто нет на экране.

    Args:
        visible_isins: ISIN-ы, которые отображаются в текущей таблице
            (источник правды для них — ``new_visible_favs``).
        new_visible_favs: подмножество ``visible_isins``, которое должно
            быть в избранном после операции.

    Returns:
        ``True``, если в файле действительно что-то изменилось.
    """
    all_favs = load_favorites()
    hidden_favs = all_favs - visible_isins
    desired_full = hidden_favs | (new_visible_favs & visible_isins)
    if desired_full == all_favs:
        return False
    save_favorites(desired_full)
    return True
