"""
Credit rating scraper.

Two complementary smart-lab endpoints are used:

1. ``/q/bonds/`` — index page that embeds ``var aBondsChartData = {"wc": [...]}``
   with the ~100 most liquid MOEX corporate bonds. One HTTP request, cheap,
   covers the heavyweight of the screener.

2. ``/q/bonds/<ISIN>/`` — per-bond page that renders ``Кредитный рейтинг`` in
   plain HTML inside a ``.linear-progress-bar__text`` div. Used as a fallback
   for issues outside the top-100 (regional / mid-cap corporate bonds).

National rating scale is uniform across both endpoints — smart-lab strips the
``ru`` prefix, ``core.bond_model.RATING_ORDER`` accepts both forms so no
normalisation is performed here.

ОФЗ and sovereign / municipal bonds usually have no rating widget on the
per-ISIN page; they are expected to be covered by the vendored
``data/ratings.json`` (``ОФЗ`` → ``ruAAA`` via ``name_ratings``).
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import logging
import re
from collections.abc import Callable, Iterable

import httpx

logger = logging.getLogger(__name__)

SMARTLAB_BONDS_URL = "https://smart-lab.ru/q/bonds/"
SMARTLAB_BOND_PAGE_URL_TEMPLATE = "https://smart-lab.ru/q/bonds/{isin}/"

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

_HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)

_CHART_VAR_TOKEN = "aBondsChartData"
_CHART_ARRAY_KEY = "wc"

# Per-ISIN page rating extractor. The "Кредитный рейтинг" row in
# ``quotes-simple-table`` contains a ``linear-progress-bar`` widget whose
# label holds the rating token, e.g.
#     <div class="quotes-simple-table__item">Кредитный рейтинг</div>
#     <div class="quotes-simple-table__item">
#         <div class="linear-progress-bar">
#             <div class="linear-progress-bar__filed …">
#                 <div class="linear-progress-bar__text">AAA</div>
# A non-greedy DOTALL match between the label and the first
# ``linear-progress-bar__text`` after it is robust to whitespace and CSS
# class drift; it intentionally accepts only national-scale tokens (letters,
# ``+`` and ``-``) so HTML noise cannot pollute the result.
_PER_ISIN_RATING_RE: re.Pattern[str] = re.compile(
    r"Кредитный рейтинг.*?linear-progress-bar__text\">\s*([A-Z+\-]+)\s*</div>",
    re.DOTALL,
)

# National rating scale tokens we accept from the source. Mirrors the keys in
# ``core.bond_model.RATING_ORDER`` (without the ``ru`` prefix, since smart-lab
# strips it). Any rating outside this whitelist is treated as malformed and
# silently skipped — protects us from junk values if the page format drifts.
VALID_RATINGS: frozenset[str] = frozenset(
    {
        "AAA",
        "AA+",
        "AA",
        "AA-",
        "A+",
        "A",
        "A-",
        "BBB+",
        "BBB",
        "BBB-",
        "BB+",
        "BB",
        "BB-",
        "B+",
        "B",
        "B-",
        "CCC",
        "CC",
        "C",
        "D",
    }
)


class RatingsScraperError(RuntimeError):
    """Raised when the rating source cannot be fetched or parsed."""


def _extract_chart_object(html: str) -> dict:
    """
    Locate ``var aBondsChartData = {...}`` in ``html`` and decode the object.

    Raises:
        RatingsScraperError: if the variable cannot be found or the JSON
            following it is malformed.
    """
    var_idx = html.find(_CHART_VAR_TOKEN)
    if var_idx < 0:
        raise RatingsScraperError(
            f"variable {_CHART_VAR_TOKEN!r} not found — page structure changed?"
        )
    obj_start = html.find("{", var_idx)
    if obj_start < 0:
        raise RatingsScraperError(f"no opening brace after {_CHART_VAR_TOKEN!r}")
    try:
        obj, _ = json.JSONDecoder().raw_decode(html[obj_start:])
    except json.JSONDecodeError as exc:
        raise RatingsScraperError(f"JSON decode failed: {exc}") from exc
    if not isinstance(obj, dict):
        raise RatingsScraperError(f"expected JSON object, got {type(obj).__name__}")
    return obj


def _is_plausible_isin(value: str) -> bool:
    """ISO 6166: 12 chars total, two-letter country code prefix."""
    return len(value) == 12 and value[:2].isalpha() and value[:2].isupper() and value[2:].isalnum()


def fetch_smartlab_bond_ratings(
    url: str = SMARTLAB_BONDS_URL,
    *,
    client: httpx.Client | None = None,
) -> dict[str, str]:
    """
    Fetch ISIN → rating map from smart-lab.

    Args:
        url: Override for the source URL (mainly for testing).
        client: Optional pre-configured ``httpx.Client``. When ``None`` a
            single-shot client with retries is created internally.

    Returns:
        Mapping ``{ISIN: rating}``. Empty dict is a valid response when the
        source returned no usable entries.

    Raises:
        RatingsScraperError: on network errors or unparseable page content.
    """
    owned_client = client is None
    if owned_client:
        client = httpx.Client(
            transport=httpx.HTTPTransport(retries=2),
            timeout=_HTTP_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        )
    assert client is not None
    try:
        try:
            resp = client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise RatingsScraperError(f"network error: {exc}") from exc
        html = resp.text
    finally:
        if owned_client:
            client.close()

    chart_obj = _extract_chart_object(html)
    entries = chart_obj.get(_CHART_ARRAY_KEY)
    if not isinstance(entries, list):
        raise RatingsScraperError(
            f"unexpected payload shape: {_CHART_VAR_TOKEN}.{_CHART_ARRAY_KEY} "
            f"is {type(entries).__name__}, expected list"
        )

    result: dict[str, str] = {}
    skipped_malformed = 0
    skipped_rating = 0
    for entry in entries:
        if not isinstance(entry, dict):
            skipped_malformed += 1
            continue
        isin = entry.get("secid")
        rating = entry.get("rating")
        if not isinstance(isin, str) or not isinstance(rating, str):
            skipped_malformed += 1
            continue
        isin = isin.strip()
        rating = rating.strip()
        if not _is_plausible_isin(isin):
            skipped_malformed += 1
            continue
        if rating not in VALID_RATINGS:
            skipped_rating += 1
            continue
        result[isin] = rating

    logger.info(
        "smart-lab: parsed %d ratings (skipped malformed=%d, unknown_rating=%d)",
        len(result),
        skipped_malformed,
        skipped_rating,
    )
    return result


# ── Per-ISIN fallback ─────────────────────────────────────────────────────────


def _build_default_client() -> httpx.Client:
    """Shared HTTP client config for per-ISIN requests."""
    return httpx.Client(
        transport=httpx.HTTPTransport(retries=2),
        timeout=_HTTP_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": _USER_AGENT},
    )


def _extract_rating_from_bond_page(html: str) -> str | None:
    """
    Extract the rating token from a per-ISIN smart-lab bond page.

    Returns ``None`` if the rating widget is absent (most often the case for
    ОФЗ, subfederal and sovereign issues) or if the extracted token is not in
    :data:`VALID_RATINGS` (defensive — page format drift).
    """
    match = _PER_ISIN_RATING_RE.search(html)
    if not match:
        return None
    rating = match.group(1).strip()
    return rating if rating in VALID_RATINGS else None


def fetch_smartlab_rating_for_isin(
    isin: str,
    *,
    client: httpx.Client,
) -> str | None:
    """
    Fetch credit rating for a single ISIN from its smart-lab bond page.

    Args:
        isin: ISO 6166 identifier (e.g. ``RU000A102LF6``).
        client: A reusable HTTP client; the caller owns its lifecycle.

    Returns:
        Rating token (``AAA``, ``B``, …) or ``None`` if the page is missing,
        the rating widget is absent, or the response is non-200.

    Notes:
        Network errors are logged and swallowed (returns ``None``) — the
        orchestrator continues with the remaining ISINs instead of aborting
        the whole batch on a single hiccup.
    """
    isin = isin.strip()
    if not _is_plausible_isin(isin):
        return None
    url = SMARTLAB_BOND_PAGE_URL_TEMPLATE.format(isin=isin)
    try:
        resp = client.get(url)
    except httpx.HTTPError as exc:
        logger.debug("per-ISIN %s: network error: %s", isin, exc)
        return None
    if resp.status_code != 200:
        logger.debug("per-ISIN %s: HTTP %d", isin, resp.status_code)
        return None
    return _extract_rating_from_bond_page(resp.text)


def fetch_smartlab_ratings_per_isin(
    isins: Iterable[str],
    *,
    concurrency: int = 8,
    client: httpx.Client | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, str]:
    """
    Fetch ratings for many ISINs in parallel from per-bond smart-lab pages.

    Args:
        isins: Iterable of ISINs. Duplicates and non-ISIN-shaped values are
            silently filtered out.
        concurrency: Number of concurrent HTTP requests. ``8`` is a balance
            between throughput and politeness for a public page; raise with
            care.
        client: Optional pre-configured ``httpx.Client`` (e.g. mocked in
            tests). When ``None`` a single-shot client with retries is
            created internally.
        progress: Optional callback invoked as ``progress(done, total)``
            after each finished request. Useful for Streamlit progress bars.

    Returns:
        ``{ISIN: rating}`` map. ISINs whose page has no rating widget (ОФЗ,
        sub-federal, sovereign) are silently omitted.
    """
    isin_list: list[str] = []
    seen: set[str] = set()
    for isin in isins:
        isin = isin.strip()
        if not _is_plausible_isin(isin) or isin in seen:
            continue
        seen.add(isin)
        isin_list.append(isin)

    total = len(isin_list)
    if progress is not None:
        progress(0, total)
    if not isin_list:
        return {}

    owned_client = client is None
    if owned_client:
        client = _build_default_client()
    assert client is not None

    result: dict[str, str] = {}
    try:
        with cf.ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            futures = {
                pool.submit(fetch_smartlab_rating_for_isin, isin, client=client): isin
                for isin in isin_list
            }
            for done_count, fut in enumerate(cf.as_completed(futures), start=1):
                isin = futures[fut]
                rating: str | None
                try:
                    rating = fut.result()
                except Exception:
                    logger.exception("per-ISIN %s: unexpected error", isin)
                    rating = None
                if rating:
                    result[isin] = rating
                if progress is not None:
                    progress(done_count, total)
    finally:
        if owned_client:
            client.close()

    logger.info(
        "smart-lab per-ISIN: fetched %d/%d ratings (no rating widget on %d pages)",
        len(result),
        total,
        total - len(result),
    )
    return result
