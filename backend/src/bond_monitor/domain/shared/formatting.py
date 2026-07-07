"""Number/money display helpers.

Centralises formatting of monetary amounts so the whole UI is consistent.

Russian-style spacing is enforced manually (Python's locale module isn't
available in every container image and Streamlit's ``column_config.format``
uses a client-side locale that we can't pin reliably):

* Thousands are separated by a non-breaking space (U+00A0) so digit groups
  don't get split across lines on narrow viewports.
* Decimal separator is a regular dot ``"."`` per the user's product spec
  (note: this departs from the GOST RF convention which uses a comma —
  it's an explicit product decision in this app).
"""

from __future__ import annotations

# U+00A0 NO-BREAK SPACE — keeps "1 234 567" together when text wraps.
_THOUSANDS_SEP: str = "\u00a0"

# Placeholder rendered when a numeric value is missing.
MISSING_VALUE: str = "—"


def format_number(value: float | int | None, *, decimals: int = 2) -> str:
    """Format ``value`` with non-breaking-space thousands separator.

    ``None`` → :data:`MISSING_VALUE` (em-dash). Negative numbers are kept
    with a leading minus sign; rounding is delegated to ``format(..)``.
    """
    if value is None:
        return MISSING_VALUE
    # f-string ',' uses comma as thousands separator — swap it out for NBSP.
    return f"{value:,.{decimals}f}".replace(",", _THOUSANDS_SEP)


def format_rub(value: float | int | None, *, decimals: int = 2) -> str:
    """Russian-style monetary string: ``"1 234 567.89 ₽"``.

    See module docstring for the formatting rationale. Returns the bare
    :data:`MISSING_VALUE` (without ``₽``) when ``value`` is ``None``,
    because trailing ``" ₽"`` after an em-dash looks broken.
    """
    if value is None:
        return MISSING_VALUE
    return f"{format_number(value, decimals=decimals)}\u00a0₽"
