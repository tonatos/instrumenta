"""
Общие фикстуры для всех тестов bond-monitor.

`sys.path` корректируется чтобы `tests/` мог импортировать `core/`, `data/`
напрямую — без установки пакета (нет `setup.py` / `pyproject.toml` для
этого проекта).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
