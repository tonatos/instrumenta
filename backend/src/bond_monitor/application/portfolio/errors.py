"""Exceptions raised by portfolio application services."""

from __future__ import annotations


class SlotOverrideValidationError(ValueError):
    """Manual reinvestment replacement failed pre-validation."""

    def __init__(self, message: str, *, code: str = "invalid_replacement") -> None:
        self.code = code
        self.message = message
        super().__init__(message)
