"""
Bond Monitor — краткосрочные облигации РФ
Streamlit application entry point.

Вкладки:
  1. Скринер    — отбор бумаг по фильтрам со скоринговой таблицей.
                  Клик по иконке ℹ️ в строке открывает страницу с деталями бумаги
                  (роутинг через query-param ``?bond=<SECID>``).
  2. Калькулятор — расчёт реальной доходности с учётом НДФЛ и НКД.

Запуск:
  streamlit run app.py
"""

from __future__ import annotations

import json
import logging
import math
import os
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from core.bond_model import (
    COUPON_TYPE_LABELS,
    RISK_LEVEL_LABELS,
    BondRecord,
    CouponType,
    RiskLevel,
)
from core.formatting import format_rub
from core.scorer import KEY_RATE_DEFAULT, TAX_RATE_DEFAULT, score_bonds
from data.favorites import (
    load_favorites,
    sync_visible_favorites,
    toggle_favorite,
)
from data.moex_client import fetch_all_bonds, is_moex_cache_fresh
from data.moex_defaults_client import enrich_bonds_with_defaults
from data.ratings_loader import (
    apply_ratings,
    load_auto_ratings,
    load_ratings,
    save_auto_ratings,
)
from data.ratings_scraper import (
    RatingsScraperError,
    fetch_smartlab_bond_ratings,
    fetch_smartlab_ratings_per_isin,
)
from data.tinvest_client import (
    enrich_bonds_from_tinvest,
    get_bond_coupon_schedule,
    resolve_coupon_type_from_schedule,
)
from ui.components import (
    DETAIL_LINK_COLUMN,
    DETAIL_QUERY_PARAM,
    FAVORITE_COLUMN,
    invalidate_editor_state,
    make_editor_key,
    render_bond_info_table,
    render_external_links,
    render_favorite_toggle_button,
    render_key_metrics,
    render_price_block,
    render_score_breakdown,
    render_screener_table,
    render_warnings,
)

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
#  Config from environment
# ──────────────────────────────────────────────

TINKOFF_TOKEN: str | None = os.getenv("TINKOFF_TOKEN") or None
KEY_RATE: float = float(os.getenv("KEY_RATE", KEY_RATE_DEFAULT))
# TAX_RATE in .env is expressed in percent (e.g. TAX_RATE=18 means 18% НДФЛ).
# Internally we work with the fraction (0.18).
TAX_RATE_PCT: float = float(os.getenv("TAX_RATE", TAX_RATE_DEFAULT * 100))
MAX_DAYS: int = int(os.getenv("MAX_DAYS", 120))
MIN_VOLUME_RUB: float = float(os.getenv("MIN_VOLUME_RUB", 500_000))


# ──────────────────────────────────────────────
#  Data loading (cached 15 min = MOEX delay)
# ──────────────────────────────────────────────


@st.cache_data(ttl=900, show_spinner=False)
def load_bonds(
    max_days: int,
    min_volume_rub: float,
    key_rate: float,
    tax_rate: float,
    token: str | None,
    filter_by: str = "effective",
) -> tuple[list[BondRecord], str]:
    """
    Full pipeline: fetch → enrich → apply ratings → score.

    ``filter_by`` controls which date the ``max_days`` cap is measured
    against:
        * ``"effective"`` — ``min(maturity_date, offer_date)`` (default;
          matches how MOEX reports YTM).
        * ``"maturity"`` — only ``maturity_date``; surfaces bonds
          guaranteed to be fully redeemed by the cap even if they have
          an earlier put-offer.

    Returns (bonds, source_description).
    """
    bonds = fetch_all_bonds(
        max_days=max_days,
        min_volume_rub=min_volume_rub,
        filter_by=filter_by,
    )
    source = "MOEX ISS API"

    # Enrich with MOEX default flags on the *post-filter* window only.
    # The /securities/{isin}.json endpoint requires one round-trip per
    # bond, but we have at most ~200 bonds in scope after the maturity +
    # liquidity filters, and the enricher uses a thread pool + 24 h disk
    # cache (cache/moex_defaults.json), so the cost is ~1-2 s on cold
    # start and ~0 s on every subsequent rerun within the day.
    bonds = enrich_bonds_with_defaults(bonds)

    if token:
        bonds = enrich_bonds_from_tinvest(bonds, token)
        source += " + T-Invest API"

    ratings = load_ratings()
    auto_ratings = load_auto_ratings()
    bonds = apply_ratings(bonds, ratings, auto_ratings=auto_ratings)
    bonds = score_bonds(bonds, key_rate=key_rate, tax_rate=tax_rate)
    return bonds, source


@st.cache_data(ttl=900, show_spinner=False)
def load_coupon_schedule(figi: str, token: str | None) -> list:
    if not figi or not token:
        return []
    return get_bond_coupon_schedule(token, figi, days_ahead=365)


# ──────────────────────────────────────────────
#  Page config
# ──────────────────────────────────────────────

st.set_page_config(
    page_title="Bond Monitor — краткосрочные облигации РФ",
    page_icon="B",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ──────────────────────────────────────────────
#  Frontend patches: same-tab nav + native shortcut passthrough
# ──────────────────────────────────────────────
#
# Streamlit's ``LinkColumn`` is rendered by glide-data-grid. Inspecting
# the Streamlit static bundle (``DataFrame.*.js``) we see two cell paths:
#
#   * ``onClickUri`` handler that runs
#     ``window.open(uri, "_blank", "noopener,noreferrer")`` for normal
#     clicks on the cell (the prevailing path for plain LinkColumn
#     cells);
#   * An overlay ``<a class="gdg-link-area" target="_blank" rel="noopener
#     noreferrer">`` element rendered when the cell enters its "edit" /
#     hover overlay state.
#
# Neither path is configurable from Python, so we install a JavaScript
# shim that intercepts BOTH paths and rewrites navigation to stay in the
# same tab while preserving browser history.
#
# We inject the shim with ``st.html(..., unsafe_allow_javascript=True)``,
# which renders the markup *inline in the top DOM* (no iframe wrapper —
# see the official docstring: "st.html content is not iframed"). That
# means our ``<script>`` runs in the same window context where Streamlit
# itself called ``window.open``, so we patch ``window.open`` directly —
# no ``window.parent`` cross-frame hops required. The earlier
# ``components.html`` based variant lived in a sandboxed srcdoc iframe;
# even with ``allow-same-origin``, click handlers fired in the parent
# window were never visible from the child, so the patch silently did
# nothing.
#
# Implementation details:
#   * The patch is guarded by ``__bondMonitorLinkPatch`` so reruns don't
#     stack handlers.
#   * It only diverts URLs that point at the same document and have a
#     non-empty query string (our ``?bond=...`` deep links). Any other
#     ``window.open`` call keeps its default new-tab behaviour, so
#     external links from other LinkColumns still open in a new tab.
#   * For the intercepted link we navigate with ``location.assign(url)``.
#     We initially tried SPA-style ``history.pushState`` + synthetic
#     ``popstate`` but Streamlit has known bugs (#13853, #13963, #9279)
#     where ``st.query_params`` returns stale values after a same-page
#     popstate. ``location.assign`` triggers a real navigation that
#     stays in the *same* tab, pushes a history entry (back/forward
#     work) and forces Streamlit to re-init with the fresh query
#     string. Re-init is fast (~1 s) thanks to ``@st.cache_data``.
#   * Modifier-aware: glide-data-grid's ``onClickUri`` strips the
#     originating ``MouseEvent`` before calling ``window.open``, so we
#     can't read modifiers from inside the override. Instead, a global
#     capture-phase ``mousedown``/``auxclick`` listener stashes the
#     latest modifier state (``metaKey``/``ctrlKey``/``shiftKey`` and
#     whether it was a middle-click) with a short timestamp. When our
#     ``window.open`` wrapper fires shortly after, it consults this
#     stash: if any "open in new tab/window" modifier was held — or it
#     was a middle-click — we hand the call to the native
#     ``window.open`` so the browser opens a new tab/window as the user
#     intended. Otherwise we redirect in the current tab.
#   * A capture-phase click listener catches the ``<a target="_blank">``
#     overlay path (and respects modifiers there as well).
#   * The ``window.open`` override re-installs itself on every animation
#     frame so any subsequent code that resets ``window.open``
#     (HMR/hot-reload/other libs) doesn't undo our patch.
#
# Additionally, Streamlit ships a small set of single-letter hotkeys via
# the bundled ``hotkeys-js`` library (the global ``window.hotkeys``):
# ``C`` opens the "Clear cache" dialog, ``R`` reruns the script, etc.
# ``hotkeys-js`` triggers on ``event.key`` regardless of modifiers, so
# pressing ``Cmd+C`` to copy text on the page also fires the Clear-cache
# dialog. We block that by ``stopImmediatePropagation()``-ing any
# ``Cmd/Ctrl`` + single-key combo in the capture phase before
# ``hotkeys-js`` sees it. The browser's native copy/paste/select-all
# still works because those are UA-level commands handled in parallel
# and don't depend on bubbling keydown listeners.
_FRONTEND_PATCH: str = """
<script>
(function () {
  const log = (...args) => {
    try { console.log('[bond-monitor]', ...args); } catch (e) {}
  };
  log('script eval at', new Date().toISOString(),
      'guard=', !!window.__bondMonitorLinkPatch);
  if (window.__bondMonitorLinkPatch) return;
  window.__bondMonitorLinkPatch = true;
  log('installing same-tab navigation patch');

  const isInternalQuery = (url) => {
    if (typeof url !== 'string' || url.length === 0) return false;
    if (url.startsWith('?')) return true;
    try {
      const parsed = new URL(url, window.location.href);
      return (
        parsed.origin === window.location.origin &&
        parsed.pathname === window.location.pathname &&
        parsed.search.length > 0
      );
    } catch (e) {
      return false;
    }
  };

  const navigateSameTab = (url) => {
    try {
      const target = new URL(url, window.location.href);
      // Сохраняем текущее ?tab=... при переходе на ?bond=<SECID> —
      // иначе при возврате с detail-страницы юзер окажется не на той
      // вкладке, с которой пришёл (см. tab-persistence ниже).
      const currentTab = new URLSearchParams(
        window.location.search
      ).get('tab');
      if (currentTab && !target.searchParams.has('tab')) {
        target.searchParams.set('tab', currentTab);
      }
      const targetStr = target.toString();
      if (targetStr !== window.location.href) {
        log('redirecting to', targetStr);
        window.location.assign(targetStr);
      }
    } catch (e) {
      log('navigateSameTab error', e);
    }
  };

  // Track the latest pointer-event modifiers so the window.open wrapper
  // (which doesn't receive the originating event) can decide whether
  // the user wanted a new tab/window. We treat the cached state as
  // stale after MODIFIER_TTL_MS to avoid carrying it across unrelated
  // interactions.
  const MODIFIER_TTL_MS = 750;
  let lastPointer = { meta: false, ctrl: false, shift: false, middle: false, at: 0 };
  const recordPointer = (event) => {
    lastPointer = {
      meta: !!event.metaKey,
      ctrl: !!event.ctrlKey,
      shift: !!event.shiftKey,
      middle: event.button === 1,
      at: performance.now(),
    };
  };
  document.addEventListener('mousedown', recordPointer, true);
  document.addEventListener('auxclick', recordPointer, true);
  // Pointerdown also fires for canvas-rendered grids on some platforms.
  document.addEventListener('pointerdown', recordPointer, true);

  const wantsNewTab = () => {
    if (performance.now() - lastPointer.at > MODIFIER_TTL_MS) return false;
    return lastPointer.meta || lastPointer.ctrl || lastPointer.shift || lastPointer.middle;
  };

  const origOpen = window.open.bind(window);
  const wrappedOpen = function (url, target, features) {
    if (isInternalQuery(url)) {
      if (wantsNewTab()) {
        log('window.open passthrough (modifier/middle-click)', url);
        return origOpen(url, target, features);
      }
      log('window.open intercepted (same tab)', url);
      navigateSameTab(url);
      return null;
    }
    return origOpen(url, target, features);
  };
  const installOpenOverride = () => {
    if (window.open !== wrappedOpen) {
      window.open = wrappedOpen;
    }
    window.requestAnimationFrame(installOpenOverride);
  };
  installOpenOverride();

  document.addEventListener('click', (event) => {
    const anchor = event.target instanceof Element
      ? event.target.closest('a[href]')
      : null;
    if (!anchor) return;
    const href = anchor.getAttribute('href');
    if (!isInternalQuery(href)) return;
    // Let the browser handle Cmd/Ctrl/Shift-click and middle-click in
    // its default way (opens in new tab/window).
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button === 1) {
      log('anchor click passthrough (modifier/middle-click)', href);
      return;
    }
    log('anchor click intercepted (same tab)', href);
    event.preventDefault();
    event.stopPropagation();
    navigateSameTab(href);
  }, true);

  // Block Streamlit's single-letter hotkeys (hotkeys-js) for any
  // Cmd/Ctrl + single-key combo so native browser shortcuts
  // (Cmd+C copy, Cmd+V paste, Cmd+A select-all, …) work instead of
  // popping the Clear-cache / Rerun dialogs. We *only* stop event
  // propagation — we never call preventDefault, so the UA's own
  // copy/paste handling proceeds normally. Plain single-letter
  // presses ("c", "r") without a modifier are left untouched so power
  // users keeping Streamlit's defaults aren't affected.
  document.addEventListener('keydown', (event) => {
    if (!(event.metaKey || event.ctrlKey)) return;
    // event.key === "Meta"/"Control"/"Alt"/"Shift" → modifier press
    // itself; "ArrowLeft"/"F1"/… have length > 1. We only care about
    // single-character chord keys (letters, digits, punctuation).
    if (typeof event.key !== 'string' || event.key.length !== 1) return;
    event.stopImmediatePropagation();
  }, true);

  // ── Tab persistence ────────────────────────────────────────────────
  //
  // Streamlit's st.tabs is stateless: every script rerun re-mounts the
  // React component, which resets the active tab to the first one. This
  // breaks the "Избранное" tab UX — снятие галочки делает st.rerun()
  // (для актуализации списка), и пользователь оказывается обратно на
  // "Скринере". Эта известная давнишняя проблема Streamlit
  // (github issue #4831 и пр.); каноничное решение — записывать
  // активную вкладку в URL и принудительно кликать её после каждого
  // ре-рендера. Делается это полностью на клиенте: ?tab=... обновляем
  // history.replaceState (без перезагрузки), а после reupdate'а DOM —
  // simulate-кликаем по нужной вкладке. Сами st.tabs живут в первом
  // элементе с ``[data-baseweb="tab-list"]``; мы предполагаем, что
  // порядок вкладок в Streamlit совпадает с порядком, в котором они
  // переданы в st.tabs(...) в Python — для нас это [screener,
  // favorites, calc]. Если перестановка вкладок в app.py меняется,
  // здесь тоже нужно поправить TAB_INDEX_TO_KEY.
  const TAB_QUERY_PARAM = 'tab';
  const TAB_INDEX_TO_KEY = ['screener', 'favorites', 'calc'];
  const TAB_KEY_TO_INDEX = Object.fromEntries(
    TAB_INDEX_TO_KEY.map((k, i) => [k, i])
  );

  // Streamlit DOM-структура для st.tabs(): обёртка
  // ``[data-testid="stTabs"]`` содержит ``<button role="tab" ...>`` —
  // по одной кнопке на каждую вкладку. Селекторы baseweb-классов
  // (``[data-baseweb="tab-list"]``) ненадёжны: проверено практикой —
  // на текущей версии Streamlit (1.x) такой узел просто не
  // присутствует, поэтому ищем напрямую ``button[role="tab"]`` внутри
  // ``stTabs``. Полагаемся на то, что в основной разметке у нас
  // ровно один блок st.tabs() с тремя кнопками-вкладками. Если в
  // будущем появится несколько st.tabs() — нужно будет различать их.
  const getTabButtons = () => {
    // Streamlit рендерит tab-headers как ``<button>`` ИЛИ ``<div>``
    // в зависимости от версии. Берём любые ``[role="tab"]`` —
    // только так селектор остаётся стабильным между апгрейдами.
    // ``[data-testid="stTabs"]``-обёртка может присутствовать или
    // отсутствовать. Если контейнер найден и в нём ровно столько
    // tab-ов, сколько мы ожидаем — выбираем его. Иначе fallback на
    // первые N tab-ов всей страницы.
    const containers = document.querySelectorAll('[data-testid="stTabs"]');
    for (const container of containers) {
      const tabs = container.querySelectorAll('[role="tab"]');
      if (tabs.length === TAB_INDEX_TO_KEY.length) {
        return Array.from(tabs);
      }
    }
    const tabs = document.querySelectorAll('[role="tab"]');
    if (tabs.length >= TAB_INDEX_TO_KEY.length) {
      return Array.from(tabs).slice(0, TAB_INDEX_TO_KEY.length);
    }
    return null;
  };

  const writeTabToUrl = (idx) => {
    const key = TAB_INDEX_TO_KEY[idx];
    if (!key) return;
    const url = new URL(window.location.href);
    if (url.searchParams.get(TAB_QUERY_PARAM) === key) return;
    url.searchParams.set(TAB_QUERY_PARAM, key);
    log('tab persisted to URL', key);
    // replaceState: меняем URL без push в history и без navigation —
    // следующий st.rerun() прочитает свежий ?tab=... через нас же.
    history.replaceState(history.state, '', url.toString());
  };

  // Capture-phase click handler: пишем активную вкладку в URL сразу,
  // когда пользователь кликает на неё. Не используем 'change'/'focus'
  // events — у Streamlit-tabs нет таких событий на самой вкладке.
  document.addEventListener('click', (event) => {
    const tabBtn = event.target instanceof Element
      ? event.target.closest('[role="tab"]')
      : null;
    if (!tabBtn) return;
    const tabs = getTabButtons();
    if (!tabs) return;
    const idx = tabs.indexOf(tabBtn);
    if (idx >= 0) writeTabToUrl(idx);
  }, true);

  // Restore active tab. Streamlit перерисовывает tab-list при каждом
  // rerun, и сразу после перерисовки активной всегда становится первая
  // вкладка. Используем requestAnimationFrame-цикл (как и для
  // window.open override) — это самый дешёвый способ ловить момент
  // перерисовки без MutationObserver на всё body. Программный click()
  // по табу не делает HTTP-запросов и не вызывает st.rerun() — это
  // чисто клиентский CSS-state change в React-компоненте.
  let lastRestoredKey = null;
  let lastRestoredAt = 0;
  let restoreTickCount = 0;
  const restoreActiveTab = () => {
    restoreTickCount++;
    if (restoreTickCount === 1 || restoreTickCount === 50 || restoreTickCount === 500) {
      const allTabs = document.querySelectorAll('[role="tab"]');
      const allStTabs = document.querySelectorAll('[data-testid="stTabs"]');
      const allButtons = document.querySelectorAll('button');
      log('restore tick', restoreTickCount, '[role=tab]=', allTabs.length, '[data-testid=stTabs]=', allStTabs.length, 'buttons=', allButtons.length);
    }
    const params = new URLSearchParams(window.location.search);
    const targetKey = params.get(TAB_QUERY_PARAM);
    if (targetKey && TAB_KEY_TO_INDEX[targetKey] !== undefined) {
      const tabs = getTabButtons();
      if (tabs) {
        const idx = TAB_KEY_TO_INDEX[targetKey];
        const target = tabs[idx];
        if (target && target.getAttribute('aria-selected') !== 'true') {
          const now = performance.now();
          if (lastRestoredKey !== targetKey || now - lastRestoredAt > 100) {
            lastRestoredKey = targetKey;
            lastRestoredAt = now;
            log('restoreActiveTab clicking', targetKey, 'idx', idx);
            target.click();
          }
        }
      }
    }
    window.requestAnimationFrame(restoreActiveTab);
  };
  restoreActiveTab();
})();
</script>
"""

st.html(_FRONTEND_PATCH, unsafe_allow_javascript=True)


# ──────────────────────────────────────────────
#  Sidebar — global config + filters
# ──────────────────────────────────────────────

with st.sidebar:
    st.title("Bond Monitor")
    st.caption("Скринер краткосрочных облигаций РФ")

    st.divider()
    st.subheader("Параметры")
    key_rate_input = st.number_input(
        "Ключевая ставка ЦБ, %",
        min_value=0.0,
        max_value=50.0,
        value=KEY_RATE,
        step=0.25,
        help="Используется как безрисковый ориентир для расчёта скора. Текущая ставка ЦБ РФ: 14,50%",
    )
    tax_rate_pct_input = st.number_input(
        "Ставка НДФЛ, %",
        min_value=0.0,
        max_value=50.0,
        value=TAX_RATE_PCT,
        step=1.0,
        help=(
            "Применяется к YTM, купонам и приросту цены. Базовая шкала РФ: "
            "13% до 2,4 млн ₽ налоговой базы в год, 15% / 18% / 20% / 22% свыше. "
            "Дефолт: 13%, override через env TAX_RATE."
        ),
    )
    tax_rate_input = tax_rate_pct_input / 100.0
    max_days_input = st.slider(
        "Макс. дней до погашения / оферты",
        min_value=1,
        max_value=360,
        value=MAX_DAYS,
        step=1,
    )
    # Determines which date the "Макс. дней" slider is measured against.
    # Default is "effective" — the minimum of maturity and put-offer
    # dates — which matches how MOEX itself reports YTM (always to the
    # closest cash-return event). Switching to "maturity" lets the user
    # screen for bonds guaranteed to be fully redeemed by a target date,
    # even if they happen to have an earlier put-offer along the way.
    filter_by_input = st.radio(
        "Считать срок до",
        options=["effective", "maturity"],
        format_func=lambda v: {
            "effective": "Ближайшей оферты или погашения",
            "maturity": "Даты погашения",
        }[v],
        index=0,
        help=(
            "«Ближайшей оферты или погашения» (по умолчанию): фильтр учитывает "
            "min(дата погашения, дата пут-оферты). YTM из MOEX считается именно к "
            "этой дате. «Даты погашения»: показывает бумаги, гарантированно "
            "погашаемые к указанному сроку — пут-оферты по этим бумагам тоже "
            "будут (раньше), но фильтр их игнорирует и смотрит только на финальную "
            "дату возврата номинала."
        ),
    )
    min_vol_input = st.number_input(
        "Мин. объём торгов, ₽/день",
        min_value=0,
        value=int(MIN_VOLUME_RUB),
        step=100_000,
        help="Фильтрует неликвидные бумаги. YTM по бумаге без сделок — несостоятельная цифра",
    )

    st.divider()
    st.subheader("Фильтры таблицы")
    coupon_type_options = [ct.value for ct in CouponType]
    filter_coupon_types = st.multiselect(
        "Тип купона",
        options=coupon_type_options,
        default=coupon_type_options,
        format_func=lambda v: COUPON_TYPE_LABELS.get(CouponType(v), v),
        help=(
            "Если T-Invest API не подключён, у большинства бумаг тип купона = «Неизвестен» — "
            "снимать галочку не рекомендуется"
        ),
    )
    # Order from lowest to highest risk so that the default list reads
    # naturally in the UI; UNKNOWN goes at the end as a separate bucket.
    risk_level_options = [
        RiskLevel.LOW.value,
        RiskLevel.MODERATE.value,
        RiskLevel.HIGH.value,
        RiskLevel.UNKNOWN.value,
    ]
    filter_risk_levels = st.multiselect(
        "Уровень риска",
        options=risk_level_options,
        default=risk_level_options,
        format_func=lambda v: RISK_LEVEL_LABELS.get(RiskLevel(v), str(v)),
        help=(
            "Оценивается по кредитному рейтингу эмитента: ruAAA…ruA → низкий, "
            "ruBBB+…ruBB- → умеренный, ниже ruBB- → высокий. "
            "У бумаг без рейтинга в `data/ratings.json` уровень = «Неизвестен»."
        ),
    )
    filter_min_ytm_net = st.number_input(
        "Мин. YTM нетто, %",
        min_value=0.0,
        max_value=50.0,
        value=0.0,
        step=0.5,
        help="Фильтрует бумаги с доходностью ниже порога после НДФЛ",
    )
    filter_max_lot_cost = st.number_input(
        "Макс. стоимость лота, ₽",
        min_value=0,
        max_value=100_000_000,
        value=0,
        step=10_000,
        help=(
            "Скрывает бумаги, 1 лот которых стоит дороже указанной суммы. "
            "0 — фильтр отключён. Учитывается грязная цена × лотность."
        ),
    )
    filter_hide_qual = st.checkbox(
        "Скрыть «только для квалинвесторов»",
        value=False,
        help="Убирает бумаги с for_qual_investor_flag",
    )
    filter_hide_subordinated = st.checkbox(
        "Скрыть субординированные",
        value=False,
        help="Убирает облигации с subordinated_flag",
    )
    filter_hide_defaulted = st.checkbox(
        "Скрыть дефолтные",
        value=True,
        help=(
            "Скрывает бумаги, у которых эмитент в дефолте или тех. дефолте "
            "(MOEX HASDEFAULT / HASTECHNICALDEFAULT). "
            "По умолчанию включено: такие бумаги торгуются с аномально "
            "большим дисконтом и искажают статистики скринера."
        ),
    )

    st.divider()
    if st.button("Обновить данные", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    if st.button(
        "Обновить рейтинги",
        use_container_width=True,
        help=(
            "Двухступенчатая загрузка рейтингов со smart-lab.ru: "
            "сначала топ-100 самых ликвидных облигаций (один запрос к /q/bonds/), "
            "затем точечные запросы /q/bonds/<ISIN>/ для бумаг скринера, "
            "не покрытых ни топ-100, ни vendored ratings.json. "
            "Результаты обоих этапов сливаются в один кэш."
        ),
    ):
        try:
            with st.spinner("Этап 1/2: загрузка топ-100 со smart-lab…"):
                top_isin_map = fetch_smartlab_bond_ratings()
        except RatingsScraperError as exc:
            st.error(f"Не удалось загрузить топ-100: {exc}")
        else:
            if not top_isin_map:
                st.warning("Источник вернул пустой список — кэш не изменён")
            else:
                with st.spinner("Этап 2/2: определение непокрытых бумаг…"):
                    screener_bonds = fetch_all_bonds(
                        max_days=max_days_input,
                        min_volume_rub=float(min_vol_input),
                    )
                    apply_ratings(
                        screener_bonds,
                        load_ratings(),
                        auto_ratings={"isin_ratings": top_isin_map},
                    )
                    uncovered_isins = [b.isin for b in screener_bonds if not b.credit_rating]

                per_isin_map: dict[str, str] = {}
                if uncovered_isins:
                    progress_bar = st.progress(
                        0.0,
                        text=f"Этап 2/2: 0 / {len(uncovered_isins)} per-ISIN запросов",
                    )

                    def _on_progress(done: int, total: int) -> None:
                        progress_bar.progress(
                            done / total if total else 1.0,
                            text=f"Этап 2/2: {done} / {total} per-ISIN запросов",
                        )

                    per_isin_map = fetch_smartlab_ratings_per_isin(
                        uncovered_isins,
                        concurrency=8,
                        progress=_on_progress,
                    )
                    progress_bar.empty()

                combined_isin_map = {**top_isin_map, **per_isin_map}
                save_auto_ratings(
                    combined_isin_map,
                    source="smart-lab.ru/q/bonds + per-ISIN",
                )
                st.cache_data.clear()
                st.toast(
                    f"Обновлено: топ-100 = {len(top_isin_map)}, "
                    f"per-ISIN = {len(per_isin_map)} / {len(uncovered_isins)}, "
                    f"всего в кэше = {len(combined_isin_map)}"
                )
                st.rerun()

    _auto = load_auto_ratings()
    if _auto:
        _updated = str(_auto.get("_updated_at", ""))[:10] or "—"
        st.caption(f"Авто-рейтинги: {_auto.get('_count', 0)} шт., обновлены {_updated}")
    else:
        st.caption("Авто-рейтинги: не загружены (нажмите «Обновить рейтинги»)")

    token_status = "T-Invest: подключён" if TINKOFF_TOKEN else "T-Invest: токен не задан"
    st.caption(token_status)
    if not TINKOFF_TOKEN:
        st.caption("Задайте TINKOFF_TOKEN в .env для флагов риска и купонных графиков")


# ──────────────────────────────────────────────
#  Load data
# ──────────────────────────────────────────────

_spinner_msg = (
    "Загрузка данных из кэша…"
    if is_moex_cache_fresh()
    else "Загрузка данных с MOEX… (первый запуск: ~20–30 с)"
)
with st.spinner(_spinner_msg):
    try:
        all_bonds, data_source = load_bonds(
            max_days=max_days_input,
            min_volume_rub=float(min_vol_input),
            key_rate=key_rate_input,
            tax_rate=tax_rate_input,
            token=TINKOFF_TOKEN,
            filter_by=filter_by_input,
        )
    except Exception as exc:
        st.error(f"Не удалось загрузить данные: {exc}")
        st.stop()

# Favorites живут отдельным слоем поверх результата ``load_bonds()``: список
# избранных меняется чаще, чем MOEX-данные, поэтому держать их вне @st.cache_data
# дешевле, чем инвалидировать весь кэш при каждом клике по звёздочке.
favorite_isins: set[str] = load_favorites()
for _bond in all_bonds:
    _bond.is_favorite = _bond.isin in favorite_isins


def apply_table_filters(bonds: list[BondRecord]) -> list[BondRecord]:
    result = bonds
    if filter_coupon_types is not None:
        ct_set = {CouponType(v) for v in filter_coupon_types}
        result = [b for b in result if b.coupon_type in ct_set]
    if filter_risk_levels is not None:
        rl_set = {RiskLevel(v) for v in filter_risk_levels}
        result = [b for b in result if b.risk_level in rl_set]
    if filter_min_ytm_net > 0:
        result = [b for b in result if b.ytm_net is not None and b.ytm_net >= filter_min_ytm_net]
    if filter_max_lot_cost > 0:
        max_cost = float(filter_max_lot_cost)
        result = [
            b for b in result if b.price_per_lot_rub is not None and b.price_per_lot_rub <= max_cost
        ]
    if filter_hide_qual:
        result = [b for b in result if not b.for_qual_investor_flag]
    if filter_hide_subordinated:
        result = [b for b in result if not b.subordinated_flag]
    if filter_hide_defaulted:
        result = [b for b in result if not (b.has_default or b.has_technical_default)]
    return result


filtered_bonds = apply_table_filters(all_bonds)


# ──────────────────────────────────────────────
#  Bond detail view (страница, открывается из таблицы скринера)
# ──────────────────────────────────────────────


def _close_detail_view() -> None:
    """Закрыть страницу деталей и вернуться к таблице скринера.

    Управление детальной страницей идёт через query-param ``?bond=<SECID>``:
    клик по иконке в LinkColumn проставляет его, кнопка «Назад» — снимает.
    """
    if DETAIL_QUERY_PARAM in st.query_params:
        del st.query_params[DETAIL_QUERY_PARAM]


def render_bond_detail_view(bond: BondRecord) -> None:
    """Полная страница деталей по одной облигации.

    Открывается из таблицы скринера по клику на иконку ℹ️ (LinkColumn,
    URL ``?bond=<SECID>``). Сверху — кнопка «Назад», далее блоки:
    ключевые метрики, предупреждения, цена/НКД, параметры бумаги,
    структура скора, купонный график.
    """
    # Update the browser tab title to "<bond name> | Bond Monitor".
    # st.set_page_config can only run once per script run, so we patch
    # ``document.title`` from JS at the top of the detail view. On
    # navigation back to the screener Streamlit re-runs from the top
    # and ``set_page_config`` resets the title to the default.
    # ``json.dumps`` produces a properly escaped JS string literal —
    # safe for arbitrary bond names (quotes, backslashes, unicode).
    detail_title = f"{bond.name or bond.secid} | Bond Monitor"
    st.html(
        f"<script>document.title = {json.dumps(detail_title)};</script>",
        unsafe_allow_javascript=True,
    )

    col_back, col_fav = st.columns([1, 5])
    with col_back:
        if st.button("← Назад к таблице", key="back_to_screener", type="secondary"):
            _close_detail_view()
            st.rerun()
    with col_fav:
        if render_favorite_toggle_button(bond, key=f"fav_toggle_detail_{bond.secid}"):
            if bond.isin:
                toggle_favorite(bond.isin)
                # Сбрасываем delta-state всех data_editor-ов на других
                # вкладках: они держат накопленные правки чекбоксов в
                # ``st.session_state``, и эти правки могут «откатить»
                # только что выполненный toggle при возврате на таблицу.
                invalidate_editor_state()
            st.rerun()

    st.subheader(bond.name)
    st.caption(f"ISIN: {bond.isin} · SECID: {bond.secid}")
    render_external_links(bond)

    render_key_metrics(bond)
    st.divider()

    col_left, col_right = st.columns([3, 2])

    with col_left:
        st.subheader("Предупреждения")
        render_warnings(bond)

        st.subheader("Цена и НКД")
        render_price_block(bond)

        st.subheader("Параметры бумаги")
        render_bond_info_table(bond)

    with col_right:
        st.subheader("Структура скора")
        render_score_breakdown(bond)

        st.subheader("Купонный график")
        next_coupon_str = bond.next_coupon_date.isoformat() if bond.next_coupon_date else "—"
        if not TINKOFF_TOKEN:
            st.info(
                "Задайте TINKOFF_TOKEN в .env для загрузки купонного расписания. "
                f"Ближайший купон из MOEX: {next_coupon_str}"
            )
            return
        if not bond.tinvest_enriched:
            st.warning(
                "Обогащение через T-Invest API не сработало (см. логи приложения — "
                "вероятно, не установлен пакет `t-tech-investments` или токен невалиден). "
                f"Ближайший купон из MOEX: {next_coupon_str}"
            )
            return
        if not bond.figi:
            st.info(
                "Облигация не найдена в каталоге T-Invest (возможно, недоступна "
                "для торговли через T-Invest или это OTC-бумага). "
                f"Ближайший купон из MOEX: {next_coupon_str}"
            )
            return

        coupons = load_coupon_schedule(bond.figi, TINKOFF_TOKEN)
        if not coupons:
            st.info("Купонные выплаты не найдены в T-Invest API.")
            return

        resolved = resolve_coupon_type_from_schedule(coupons)
        if bond.coupon_type == CouponType.UNKNOWN:
            bond.coupon_type = resolved

        dates = [c.payment_date.isoformat() if c.payment_date else "?" for c in coupons]
        amounts = [c.amount_rub or 0 for c in coupons]
        colors = ["#3182bd" if c.coupon_type_raw in (1, 2) else "#e6550d" for c in coupons]

        fig = go.Figure(
            go.Bar(
                x=dates,
                y=amounts,
                marker_color=colors,
                text=[format_rub(a) for a in amounts],
                textposition="outside",
            )
        )
        fig.update_layout(
            title="Предстоящие купонные выплаты",
            xaxis_title="Дата выплаты",
            yaxis_title="Сумма, ₽",
            height=320,
            margin={"t": 80, "b": 40, "l": 40, "r": 20},
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)
        total_upcoming = sum(amounts)
        st.caption(
            f"Итого предстоящих выплат: {format_rub(total_upcoming)}/облигацию "
            f"({len(coupons)} купона/ов)"
        )


# Какой бумаге (если есть) нужно показать страницу деталей в текущем прогоне.
# Источник истины — query-param ``?bond=<SECID>``. Это даёт shareable deep-link
# на детальную страницу и работает с навигацией браузера (back/forward).
detail_secid: str | None = st.query_params.get(DETAIL_QUERY_PARAM)
detail_bond: BondRecord | None = None
if detail_secid:
    detail_bond = next((b for b in all_bonds if b.secid == detail_secid), None)
    if detail_bond is None:
        # Бумага исчезла из выдачи (например, изменились фильтры/кэш) —
        # снимаем параметр и возвращаемся к скринеру.
        _close_detail_view()


# ──────────────────────────────────────────────
#  Tabs
# ──────────────────────────────────────────────

# ВАЖНО: labels вкладок должны быть СТАБИЛЬНЫМИ между rerun-ами.
# Streamlit идентифицирует вкладку по label, и если label меняется
# (например, потому что мы хотели показать счётчик "Избранное (N)"),
# Streamlit считает это другой вкладкой и сбрасывает активную на
# первую — пользователь, удаливший бумагу со вкладки «Избранное»,
# внезапно оказывается на «Скринере». Поэтому в самом label держим
# просто «Избранное», а счётчик навешиваем поверх через CSS-badge
# (см. ниже): ::after-псевдоэлемент не влияет на текст label-а, и
# идентификация вкладки Streamlit-ом остаётся стабильной.
tab_screener, tab_favorites, tab_calc = st.tabs(
    [
        "Скринер",
        "Избранное",
        "Калькулятор",
    ]
)

# Счётчик-«пилюля» на вкладке «Избранное».
#
# Реализован как CSS ``::after`` на втором табе ``role="tab"`` внутри
# единственного ``stTabs`` контейнера на странице. ``content`` —
# строковая константа (число подставляется в f-string на каждом rerun),
# поэтому смена количества избранных не меняет HTML-текст label-а и не
# триггерит сброс активной вкладки в Streamlit. При нулевом счётчике
# CSS не инжектится, чтобы вкладка не несла бесполезный «0».
#
# Цвета через ``currentColor`` + полупрозрачный фон, чтобы пилюля
# одинаково читалась в светлой и тёмной темах.
if favorite_isins:
    _favorites_count = len(favorite_isins)
    st.html(
        f"""
        <style>
        div[data-testid="stTabs"] [role="tablist"] > button[role="tab"]:nth-of-type(2)::after {{
            content: "{_favorites_count}";
            display: inline-block;
            margin-left: 8px;
            padding: 1px 8px;
            min-width: 1.4em;
            background: rgba(127, 127, 127, 0.22);
            color: currentColor;
            border-radius: 999px;
            font-size: 0.78em;
            font-weight: 600;
            line-height: 1.4;
            text-align: center;
            vertical-align: 1px;
        }}
        </style>
        """
    )


# ══════════════════════════════════════════════
#  TAB 1: Скринер  (включает страницу деталей по клику на строку)
# ══════════════════════════════════════════════

with tab_screener:
    if detail_bond is not None:
        render_bond_detail_view(detail_bond)
    else:
        risk_free_net = key_rate_input * (1.0 - tax_rate_input)
        col_a, col_b, col_c, col_d = st.columns(4)
        col_a.metric("Найдено облигаций", len(filtered_bonds))
        col_b.metric(
            "Ключевая ставка",
            f"{key_rate_input:.2f}%",
            help=(
                f"Безрисковая нетто (после НДФЛ {tax_rate_pct_input:.1f}%): {risk_free_net:.2f}%"
            ),
        )

        ytm_values = [b.ytm_net for b in filtered_bonds if b.ytm_net is not None]
        avg_ytm = sum(ytm_values) / len(ytm_values) if ytm_values else None
        col_c.metric(
            "Ср. YTM нетто",
            f"{avg_ytm:.2f}%" if avg_ytm else "—",
            delta=f"+{avg_ytm - risk_free_net:.2f}% к безриск." if avg_ytm else None,
        )
        score_values = [b.score for b in filtered_bonds if b.score is not None]
        avg_score = sum(score_values) / len(score_values) if score_values else None
        col_d.metric("Ср. скор", f"{avg_score:.1f}" if avg_score else "—")

        filter_by_label = {
            "effective": "до ближайшей оферты/погашения",
            "maturity": "до даты погашения",
        }.get(filter_by_input, "до ближайшей оферты/погашения")
        st.caption(
            f"Источники данных: {data_source} · задержка MOEX 15 мин · "
            f"критерии: срок ≤{max_days_input} дней ({filter_by_label}), "
            f"объём ≥{format_rub(min_vol_input, decimals=0)}/день · "
            "клик по ℹ️ открывает деталь в этой же вкладке "
            "(Cmd/Ctrl-клик — в новой вкладке, Shift-клик — в новом окне) · "
            "галочка в первой колонке — добавляет/убирает бумагу из избранного"
        )
        st.divider()

        if not filtered_bonds:
            st.info("По заданным фильтрам облигаций не найдено. Попробуйте смягчить условия.")
        else:
            _screener_editor_key = make_editor_key("screener_editor", filtered_bonds)
            edited_screener_df = render_screener_table(
                filtered_bonds,
                editor_key=_screener_editor_key,
            )
            # Чекбокс избранного — единственный редактируемый столбец;
            # на каждом rerun сверяем колонку с текущим состоянием и
            # синхронизируем JSON-файл. ``sync_visible_favorites``
            # бережно мерджит с уже сохранёнными ISIN-ами вне текущей
            # выдачи, а если что-то реально изменилось — мы сбрасываем
            # delta-state всех data_editor-ов и делаем ``st.rerun()``:
            # без этого следующий клик мог бы наложиться поверх старой
            # delta и «отменить» сам себя (баг «каждый второй клик не
            # срабатывает»).
            _new_visible_favs: set[str] = {
                bond.isin
                for bond, is_fav in zip(
                    filtered_bonds,
                    edited_screener_df[FAVORITE_COLUMN].tolist(),
                    strict=True,
                )
                if is_fav and bond.isin
            }
            if sync_visible_favorites(
                visible_isins={b.isin for b in filtered_bonds if b.isin},
                new_visible_favs=_new_visible_favs,
            ):
                invalidate_editor_state()
                st.rerun()

            from ui.components import build_screener_dataframe

            # В экспорт уходит таблица БЕЗ служебной URL-колонки «Детали»
            # и BOOL-колонки «Избранное»: они имеют смысл только в UI.
            df_export = build_screener_dataframe(filtered_bonds).drop(
                columns=[DETAIL_LINK_COLUMN, FAVORITE_COLUMN], errors="ignore"
            )
            st.download_button(
                "Скачать CSV",
                data=df_export.to_csv(index=False, encoding="utf-8-sig"),
                file_name=f"bonds_{date.today().isoformat()}.csv",
                mime="text/csv",
            )

        with st.expander("Как работает скоринг"):
            after_tax_mult = 1.0 - tax_rate_input
            st.markdown(f"""
**Формула:** `Скор = YTM_скор × 40% + Риск_скор × 40% + Ликвидность_скор × 20%`

| Компонент | Описание |
|-----------|----------|
| **YTM_скор** | Нормированный спред доходности (нетто) сверх безрисковой ставки. Бумага с доходностью ≤ КС × {after_tax_mult:.2f} (после НДФЛ {tax_rate_pct_input:.1f}%) получает 0. Лидер вселенной — 100. |
| **Риск_скор** | Начинается с базы по уровню риска T-Invest: Низкий→80, Умеренный→55, Высокий→25. Штрафы: амортизация −5, плавающий купон −10, субординация −30, колл-оферта −5. Бонус/штраф от кредитного рейтинга. |
| **Ликвидность_скор** | `log10(объём) / log10(макс_объём) × 100`. Логарифмическая шкала, т.к. объёмы отличаются на порядки. |

**Предупреждение:** Скор — это инструмент первичного отсева, а не инвестиционная рекомендация.
Всегда проверяйте детали бумаги перед покупкой. YTM рассчитан MOEX по средневзвешенной
цене — для неликвидных бумаг может быть неактуальным.
            """)


# ══════════════════════════════════════════════
#  TAB 2: Избранное
# ══════════════════════════════════════════════
#
# Список избранных хранится в ``cache/favorites.json`` по ISIN (см.
# data.favorites). Здесь мы пересекаем сохранённые ISIN-ы с актуальным
# окном ``all_bonds`` — то есть с тем, что MOEX отдаёт под текущие
# параметры в сайдбаре. Если избранная бумага не пролезла под фильтры
# (слишком длинная или менее ликвидная), пользователю показывается
# подсказка с числом «невидимых» избранных и инструкцией расширить
# параметры. Это сознательное упрощение для v1: отдельно фетчить
# бумаги вне основного окна — отдельная история по производительности
# (см. AGENTS.md / расширение источников).

with tab_favorites:
    if detail_bond is not None:
        # Detail-view рендерится в tab_screener. Дублировать его здесь нельзя:
        # widget-ключи (``back_to_screener``, ``fav_toggle_detail_*``)
        # уникальны в пределах одного прогона, поэтому повторный вызов
        # ``render_bond_detail_view`` упал бы с DuplicateWidgetID.
        st.info(
            "Открыта страница деталей бумаги — она показана на вкладке «Скринер». "
            "Нажмите «← Назад к таблице», чтобы вернуться к списку избранного."
        )
    elif not favorite_isins:
        st.info(
            "Список избранного пуст. Поставьте галочку в первой колонке "
            "таблицы скринера или нажмите «В избранное» на странице деталей — "
            "и бумага появится здесь."
        )
    else:
        favorite_bonds = [b for b in all_bonds if b.isin in favorite_isins]
        favorite_bonds_filtered = apply_table_filters(favorite_bonds)
        hidden_by_filters = len(favorite_bonds) - len(favorite_bonds_filtered)
        # ISIN-ы, которые в принципе не пришли с MOEX под текущие
        # параметры макс. срока / мин. объёма — отличаем их от тех, что
        # отфильтрованы только боковыми фильтрами.
        not_in_window = favorite_isins - {b.isin for b in all_bonds}

        st.subheader(f"Избранное · {len(favorite_isins)} бумаг(а)")
        st.caption(
            "Снимите галочку, чтобы убрать бумагу из избранного. "
            "ℹ️ — детали. Состав колонок и боковые фильтры — те же, что в скринере."
        )

        if not_in_window:
            st.warning(
                f"{len(not_in_window)} бумаг(и) в избранном не попали в текущее "
                "окно MOEX. Увеличьте «Макс. дней до погашения» и/или "
                "уменьшите «Мин. объём торгов» в сайдбаре, чтобы их увидеть."
            )
        if hidden_by_filters > 0:
            st.info(
                f"Ещё {hidden_by_filters} бумаг(а) скрыты текущими боковыми "
                "фильтрами (тип купона, риск, YTM, флаги). Снимите фильтры, "
                "если нужно увидеть их."
            )

        if not favorite_bonds_filtered:
            st.info(
                "Под текущими фильтрами нет видимых избранных бумаг. "
                "Снимите часть фильтров или смягчите параметры окна."
            )
        else:
            _favorites_editor_key = make_editor_key("favorites_editor", favorite_bonds_filtered)
            edited_favorites_df = render_screener_table(
                favorite_bonds_filtered,
                editor_key=_favorites_editor_key,
            )
            # Та же синхронизация, что и в скринере: visible_isins здесь —
            # ISIN-ы, реально показанные на этой вкладке (с учётом боковых
            # фильтров). Снятие галочки удалит бумагу ИЗ ИЗБРАННОГО, не
            # затрагивая ISIN-ы, которых сейчас на экране нет.
            _new_visible_favs_tab = {
                bond.isin
                for bond, is_fav in zip(
                    favorite_bonds_filtered,
                    edited_favorites_df[FAVORITE_COLUMN].tolist(),
                    strict=True,
                )
                if is_fav and bond.isin
            }
            if sync_visible_favorites(
                visible_isins={b.isin for b in favorite_bonds_filtered if b.isin},
                new_visible_favs=_new_visible_favs_tab,
            ):
                invalidate_editor_state()
                st.rerun()


# ══════════════════════════════════════════════
#  TAB 3: Калькулятор
# ══════════════════════════════════════════════

with tab_calc:
    st.subheader("Портфельный калькулятор")
    st.caption(
        "Рассчитывает реальную доходность с учётом НДФЛ, НКД и структуры купонов. "
        "Все расчёты — приближённые: используют текущие рыночные данные без прогноза изменения цены."
    )

    if not filtered_bonds:
        st.info("Нет данных. Вернитесь на вкладку Скринер и проверьте фильтры.")
        st.stop()

    budget = st.number_input(
        "Сумма инвестиций, ₽",
        min_value=1_000,
        max_value=100_000_000,
        value=100_000,
        step=10_000,
        help="Общий бюджет для расчёта. Учитывает минимальный лот каждой бумаги.",
    )

    bond_labels = [f"{b.secid} — {b.name}" for b in filtered_bonds]
    selected_labels = st.multiselect(
        "Выберите облигации для анализа (до 5)",
        options=bond_labels,
        default=bond_labels[: min(3, len(bond_labels))],
        max_selections=5,
    )

    if not selected_labels:
        st.info("Выберите хотя бы одну облигацию.")
        st.stop()

    label_to_bond = {f"{b.secid} — {b.name}": b for b in filtered_bonds}
    selected_bonds = [label_to_bond[lbl] for lbl in selected_labels if lbl in label_to_bond]

    # ── Per-bond calculation ──────────────────

    def _calc_bond(bond: BondRecord, budget_rub: float, tax_rate: float) -> dict:
        """
        Compute investment metrics for one bond given a budget.

        Tax rules applied:
          - ``tax_rate`` on all coupon income
          - ``tax_rate`` on price appreciation (face_value - clean_purchase_price)
            if bought below par
          - Price loss (bought above par) reduces taxable base only within the same
            tax year; for simplicity we cap price tax at 0 (conservative).
        """
        fv = bond.face_value
        lp = bond.last_price or 0.0
        aci = bond.accrued_interest or 0.0
        cr = bond.coupon_rate or 0.0
        days = bond.days_to_maturity or 1
        lot = bond.lot_size or 1

        clean_price_rub = lp / 100.0 * fv
        dirty_price_rub = clean_price_rub + aci
        lot_cost_rub = dirty_price_rub * lot

        if lot_cost_rub <= 0:
            return {"Наименование": bond.name, "Ошибка": "Нет данных о цене"}

        max_lots = math.floor(budget_rub / lot_cost_rub)
        if max_lots < 1:
            return {
                "Наименование": bond.name,
                "Ошибка": (
                    f"Недостаточно средств (нужно ≥ {format_rub(lot_cost_rub, decimals=0)} на 1 лот)"
                ),
            }

        n_bonds = max_lots * lot
        total_invested = n_bonds * dirty_price_rub  # including НКД
        remaining_budget = budget_rub - total_invested

        # Approximate total coupon income (НКД is returned with first coupon)
        # = coupon_rate/100 * face_value * (days/365) × n_bonds
        total_coupon_gross = cr / 100.0 * fv * (days / 365.0) * n_bonds

        # Price difference at redemption
        price_gain_per_bond = fv - clean_price_rub  # positive if below par, negative above
        total_price_change = price_gain_per_bond * n_bonds

        # Gross profit = coupon income + price change (НКД cancels: paid at buy, returned in coupon)
        total_gross = total_coupon_gross + total_price_change

        tax_coupon = total_coupon_gross * tax_rate
        # Tax on price appreciation only (not on losses in this simplified model)
        tax_price = max(0.0, total_price_change) * tax_rate
        total_tax = tax_coupon + tax_price

        total_net = total_gross - total_tax

        # Annualized net yield (simple, not compound)
        annualized_net_yield = (
            total_net / total_invested * (365.0 / days) * 100.0
            if total_invested > 0 and days > 0
            else 0.0
        )

        return {
            "Наименование": bond.name,
            "Тикер": bond.secid,
            "Куплено, шт.": n_bonds,
            "Лотов": max_lots,
            "Вложено, ₽": round(total_invested, 0),
            "В т.ч. НКД, ₽": round(aci * n_bonds, 0),
            "Остаток бюджета, ₽": round(remaining_budget, 0),
            "Купонный доход (брутто), ₽": round(total_coupon_gross, 0),
            "Изменение цены, ₽": round(total_price_change, 0),
            "Валовая прибыль, ₽": round(total_gross, 0),
            "НДФЛ, ₽": round(total_tax, 0),
            "Чистая прибыль, ₽": round(total_net, 0),
            "YTM нетто факт., %": round(annualized_net_yield, 2),
            "YTM нетто MOEX, %": round(bond.ytm_net, 2) if bond.ytm_net else None,
        }

    results = [_calc_bond(b, budget, tax_rate_input) for b in selected_bonds]

    # Separate errors from successes
    errors = [r for r in results if "Ошибка" in r]
    successes = [r for r in results if "Ошибка" not in r]

    for e in errors:
        st.warning(f"{e.get('Наименование', '?')}: {e['Ошибка']}")

    if successes:
        df_results = pd.DataFrame(successes)
        # Highlight key columns
        display_cols = [
            "Наименование",
            "Тикер",
            "Куплено, шт.",
            "Вложено, ₽",
            "В т.ч. НКД, ₽",
            "Чистая прибыль, ₽",
            "НДФЛ, ₽",
            "YTM нетто факт., %",
            "YTM нетто MOEX, %",
        ]
        display_cols = [c for c in display_cols if c in df_results.columns]
        # Same sprintf-js NBSP-thousands format used by the screener table
        # (kept inline to avoid a UI ↔ app import cycle).
        rub_format_int = "%'\u00a0,.0f"

        st.dataframe(
            df_results[display_cols],
            hide_index=True,
            use_container_width=True,
            column_config={
                "YTM нетто факт., %": st.column_config.ProgressColumn(
                    "YTM нетто расч., %",
                    help="Расчётная нетто-доходность (простая, годовая)",
                    format="%.2f%%",
                    min_value=0,
                    max_value=30,
                ),
                "YTM нетто MOEX, %": st.column_config.NumberColumn(
                    "YTM нетто MOEX, %",
                    help=(
                        f"Нетто-доходность по данным MOEX "
                        f"(YTM × {1.0 - tax_rate_input:.2f}, НДФЛ {tax_rate_pct_input:.1f}%)"
                    ),
                    format="%.2f%%",
                ),
                "Вложено, ₽": st.column_config.NumberColumn(format=rub_format_int),
                "Чистая прибыль, ₽": st.column_config.NumberColumn(format=rub_format_int),
                "НДФЛ, ₽": st.column_config.NumberColumn(format=rub_format_int),
                "В т.ч. НКД, ₽": st.column_config.NumberColumn(format=rub_format_int),
            },
        )

        # Summary row
        total_invested_sum = sum(r.get("Вложено, ₽", 0) for r in successes)
        total_net_sum = sum(r.get("Чистая прибыль, ₽", 0) for r in successes)
        total_tax_sum = sum(r.get("НДФЛ, ₽", 0) for r in successes)

        st.divider()
        sc1, sc2, sc3 = st.columns(3)
        sc1.metric("Итого вложено", format_rub(total_invested_sum, decimals=0))
        sc2.metric("Итого НДФЛ", format_rub(total_tax_sum, decimals=0))
        sc3.metric("Итого чистая прибыль", format_rub(total_net_sum, decimals=0))

        with st.expander("Методология расчёта (важно прочитать)"):
            st.markdown(f"""
**Допущения расчёта:**
- Облигация удерживается до даты погашения / пут-оферты (не продаётся до этой даты).
- Купонный доход рассчитывается как `купонная_ставка × номинал × (дней/365)` — это аппроксимация для оставшегося срока (без детального купонного расписания).
- НКД, уплаченный при покупке, возвращается с первым купонным платежом и не включается в налоговую базу по купонам.
- НДФЛ на купоны: **{tax_rate_pct_input:.1f}%** от всего купонного дохода.
- НДФЛ на курсовую разницу: **{tax_rate_pct_input:.1f}%** от положительной разницы `(номинал − чистая цена покупки)` при погашении. Отрицательная разница (куплено выше номинала) снижает налоговую базу, но в данном расчёте это не учтено (консервативная оценка).
- Амортизационные облигации: расчёт не учитывает промежуточные выплаты номинала — фактическая доходность может отличаться.
- Флоатеры: купонная ставка фиксирована как текущая — будущие изменения ставки не учитываются.
- Ставка НДФЛ настраивается в сайдбаре / через env `TAX_RATE`.

**Для точного расчёта** используйте полное купонное расписание из T-Invest API (страница деталей бумаги — открывается кликом по иконке ℹ️ в строке скринера).
            """)
