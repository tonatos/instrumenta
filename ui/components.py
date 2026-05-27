"""
Reusable Streamlit UI helper functions.

All functions in this module call st.* directly and have no return value,
unless they produce a derived data structure (e.g. a DataFrame for display).
"""

from __future__ import annotations

import hashlib
import html

import pandas as pd
import streamlit as st

from core.bond_model import (
    COUPON_TYPE_LABELS,
    RISK_LEVEL_LABELS,
    BondRecord,
    CouponType,
)
from core.formatting import MISSING_VALUE, format_number, format_rub

# sprintf-js format strings for st.column_config.NumberColumn.
# Streamlit ships a sprintf-js fork (see Streamlit's
# frontend/static/.../sprintfjs.*.js) that adds a ``,`` / ``_`` flag right
# after the optional ``'<char>`` pad-char to enable digit grouping; when
# the pad-char is set, it is reused as the group separator. So
# ``%'\u00a0,.2f`` means: pad with NBSP, group thousands with NBSP, two
# decimals — yielding e.g. ``1\u00a0234\u00a0567.89``, matching the
# Python-side ``format_rub`` output.
_RUB_FORMAT_2DP: str = "%'\u00a0,.2f"  # 1 234 567.89
_RUB_FORMAT_1DP: str = "%'\u00a0,.1f"  # 1 234.5

# Column name for the clickable "open detail page" link in the screener table.
# Exported so the CSV-export caller can drop it (URLs don't belong in exports).
DETAIL_LINK_COLUMN: str = "Детали"

# Query-param key carrying the SECID of the bond whose detail page should be
# shown. The link in DETAIL_LINK_COLUMN points at "?{DETAIL_QUERY_PARAM}=SECID";
# app.py reads the param from ``st.query_params`` to drive routing.
DETAIL_QUERY_PARAM: str = "bond"

# Column name for the boolean "is favorite" CheckboxColumn in the screener
# table. Backed by st.data_editor so the toggle happens via the standard
# Streamlit widget protocol (WebSocket round-trip, no full page reload) —
# this preserves table sort/scroll state and sidebar filter widgets.
FAVORITE_COLUMN: str = "Избранное"

# Public T-Bank bond catalog page; addressed by ISIN.
# Example: RU000A109908 → https://www.tbank.ru/invest/bonds/RU000A109908/
_TBANK_BOND_URL_TEMPLATE: str = "https://www.tbank.ru/invest/bonds/{isin}/"

# ──────────────────────────────────────────────
#  Score colour helpers
# ──────────────────────────────────────────────


def score_tone(score: float | None) -> str:
    """Return a Streamlit metric delta_color-compatible tone string."""
    if score is None:
        return "off"
    if score >= 65:
        return "normal"  # green
    if score >= 35:
        return "off"  # grey
    return "inverse"  # red


def _score_bg(score: float | None) -> str:
    if score is None or score == 0:
        return "#f0f0f0"
    if score >= 65:
        return "#d4edda"
    if score >= 35:
        return "#fff3cd"
    return "#f8d7da"


# ──────────────────────────────────────────────
#  DataFrame formatter for screener table
# ──────────────────────────────────────────────


def build_screener_dataframe(bonds: list[BondRecord]) -> pd.DataFrame:
    """Convert a list of BondRecord to a display-ready DataFrame."""
    rows = []
    for b in bonds:
        risk_label = RISK_LEVEL_LABELS.get(b.risk_level, "—")
        coupon_label = COUPON_TYPE_LABELS.get(b.coupon_type, "—")
        flags: list[str] = []
        if b.has_default:
            flags.append("Дефолт")
        if b.has_technical_default:
            flags.append("Тех.деф.")
        if b.amortization_flag:
            flags.append("Аморт.")
        if b.floating_coupon_flag or b.coupon_type == CouponType.FLOATING:
            flags.append("Флоат.")
        if b.subordinated_flag:
            flags.append("Субор.")
        if b.for_qual_investor_flag:
            flags.append("Квал.")
        if b.call_date:
            flags.append("Колл")

        lot_cost = b.price_per_lot_rub

        rows.append(
            {
                # Relative URL → clicking the link reruns the app with this
                # query param set; app.py reads it to render the detail page.
                DETAIL_LINK_COLUMN: f"?{DETAIL_QUERY_PARAM}={b.secid}",
                # Boolean: rendered as a checkbox by st.data_editor.
                FAVORITE_COLUMN: bool(b.is_favorite),
                # "#": i,
                "Скор": round(b.score, 1) if b.score is not None else None,
                "YTM нетто, %": round(b.ytm_net, 2) if b.ytm_net is not None else None,
                "Наименование": b.name,
                "Дней": b.days_to_maturity,
                # Show maturity and put-offer dates in separate columns so
                # the user can immediately see whether the bond has a
                # short put-offer that the screener is pricing against.
                "Погашение": b.maturity_date.isoformat() if b.maturity_date else "—",
                "Оферта": b.offer_date.isoformat() if b.offer_date else "—",
                "Тикер": b.secid,
                "YTM, %": round(b.ytm, 2) if b.ytm is not None else None,
                "Купон": coupon_label,
                "Рейтинг": b.credit_rating or "—",
                "Объём, млн ₽": round((b.volume_rub or 0) / 1_000_000, 1),
                "Риск": risk_label,
                "Флаги": ", ".join(flags) if flags else "—",
                "Цена лота, ₽": round(lot_cost, 2) if lot_cost is not None else None,
            }
        )

    return pd.DataFrame(rows)


def render_screener_table(bonds: list[BondRecord], *, editor_key: str) -> pd.DataFrame:
    """Render the bond screener table as an interactive data_editor.

    Two left-pinned action columns (без заголовков) визуально образуют
    одну группу: clickable Material info icon (``LinkColumn``) для
    открытия страницы деталей и чекбокс (``CheckboxColumn``) для
    избранного.

    Чекбокс редактируется через стандартный механизм ``st.data_editor``,
    то есть переключение состояния идёт через тот же WebSocket-канал
    Streamlit, что и любые виджеты сайдбара — без полной перезагрузки
    страницы (значит, фильтры, скролл и порядок сортировки сохраняются).
    Все остальные колонки отмечены ``disabled``, поэтому ячейки не редактируются.

    ``editor_key`` должен быть уникальным в пределах прогона и стабильным
    между прогонами с одинаковым составом бумаг / одинаковыми ISIN-ами в
    избранном — иначе сессия редактора будет каждый раз сбрасываться. На
    практике вызывающий код собирает его через :func:`make_editor_key`.

    Возвращает DataFrame с учётом пользовательских правок — вызывающий
    код использует его для детекции diff-а по колонке ``FAVORITE_COLUMN``
    и персистенции через :func:`data.favorites.sync_visible_favorites`.
    """
    df = build_screener_dataframe(bonds)
    edited_df = st.data_editor(
        df,
        use_container_width=True,
        hide_index=True,
        height="content",
        key=editor_key,
        # Все колонки, кроме чекбокса избранного, read-only. Для
        # LinkColumn это эквивалентно disabled=True в column_config —
        # ссылка остаётся кликабельной, текстовое редактирование URL
        # запрещено.
        disabled=[c for c in df.columns if c != FAVORITE_COLUMN],
        column_config={
            DETAIL_LINK_COLUMN: st.column_config.LinkColumn(
                # Пустой label: визуально склеиваем две action-колонки
                # в одну группу без заголовков.
                "",
                help="Открыть страницу с деталями этой бумаги",
                # Material info icon — displayed identically in every row.
                display_text=":material/info:",
                pinned=True,
                width="small",
            ),
            FAVORITE_COLUMN: st.column_config.CheckboxColumn(
                "",
                help=(
                    "Добавить/убрать бумагу из избранного. "
                    "Изменение сохраняется автоматически и доступно "
                    "на вкладке «Избранное»"
                ),
                pinned=True,
                width="small",
                default=False,
            ),
            "#": st.column_config.NumberColumn(width="small"),
            "Скор": st.column_config.ProgressColumn(
                "Скор",
                help="Совокупный скор качества (0—100): YTM×40% + Риск×40% + Ликвидность×20%",
                format="%.1f",
                min_value=0,
                max_value=100,
                width="small",
            ),
            "Наименование": st.column_config.TextColumn(width="middle"),
            "Дней": st.column_config.NumberColumn(
                "Дней до даты",
                help="Дней до ближайшей из дат: погашение или пут-оферта",
                format="%d",
                width="small",
            ),
            "Погашение": st.column_config.TextColumn(
                "Погашение",
                help="Дата возврата номинала эмитентом — финальная точка жизни облигации",
                width="small",
            ),
            "Оферта": st.column_config.TextColumn(
                "Пут-оферта",
                help=(
                    "Дата, в которую инвестор может потребовать у эмитента "
                    "досрочный выкуп облигации по 100% номинала. Если ближе "
                    "даты погашения — YTM считается именно к ней"
                ),
                width="small",
            ),
            "Цена лота, ₽": st.column_config.NumberColumn(
                "Цена лота, ₽",
                help=(
                    "Стоимость покупки 1 лота (грязная цена × лотность) — "
                    "минимальная сумма для входа в бумагу"
                ),
                format=_RUB_FORMAT_2DP,
                # Lot prices can exceed 1 000 000 ₽; the NBSP-grouped
                # 2-decimal string (e.g. "1 046 170.00") needs ~160 px to
                # avoid right-side clipping. "small" (75 px) is too
                # narrow, "medium" (200 px) wastes horizontal space.
                width="stretch",
            ),
            "YTM, %": st.column_config.NumberColumn(
                "YTM брутто",
                help="Доходность к погашению до уплаты НДФЛ",
                format="%.2f%%",
                width="small",
            ),
            "YTM нетто, %": st.column_config.NumberColumn(
                "YTM нетто",
                help="Доходность после НДФЛ (ставка настраивается в сайдбаре)",
                format="%.2f%%",
                width="small",
            ),
            "Купон": st.column_config.TextColumn(width="stretch"),
            "Рейтинг": st.column_config.TextColumn(width="small"),
            "Объём, млн ₽": st.column_config.NumberColumn(
                "Объём, млн ₽",
                help="Объём торгов за день на MOEX",
                format=_RUB_FORMAT_1DP,
                width="small",
            ),
            "Риск": st.column_config.TextColumn("Ур. риска", width="small"),
            "Флаги": st.column_config.TextColumn(
                "Флаги риска",
                help=(
                    "Дефолт — эмитент в дефолте (MOEX HASDEFAULT); "
                    "Тех.деф. — технический дефолт (MOEX HASTECHNICALDEFAULT); "
                    "Аморт. — амортизация; Флоат. — плавающий купон; "
                    "Субор. — субординирован; Квал. — только для квалинвесторов; "
                    "Колл — колл-оферта"
                ),
                width="stretch",
            ),
            "Тикер": st.column_config.TextColumn(width="stretch"),
        },
    )
    return edited_df


def make_editor_key(prefix: str, bonds: list[BondRecord]) -> str:
    """
    Стабильный ключ для ``st.data_editor`` по составу строк.

    Ключ ОДНОЗНАЧНО зависит только от упорядоченного списка SECID-ов —
    то есть от структуры самой таблицы, а НЕ от состояния избранного.
    Это критично: если бы ключ менялся после каждого клика по чекбоксу
    избранного (через смену состояния favorites), Streamlit пересоздавал
    бы виджет, и delta-state очередного клика — который сохраняется
    под старым ключом — терялся бы. Это давало бы эффект «каждый
    второй клик не срабатывает» / «удалить не получается».

    Инвалидацию delta-state после успешного save вызывающий код делает
    явно через :func:`invalidate_editor_state` — это не дублирует работу
    Streamlit, а гарантирует, что устаревшие правки не применятся поверх
    свежих данных, которые мы уже сохранили в файл.
    """
    secids = "|".join(b.secid for b in bonds)
    digest = hashlib.md5(secids.encode()).hexdigest()[:12]
    return f"{prefix}_{digest}"


# Префиксы ключей в ``st.session_state``, под которыми лежит delta-state
# редакторов скринера и избранного. Используются ``invalidate_editor_state``
# для сброса всех редакторов сразу — нужно после save favorites.json,
# чтобы накопленные ранее правки не «откатывали» свежее состояние.
SCREENER_EDITOR_PREFIX: str = "screener_editor_"
FAVORITES_EDITOR_PREFIX: str = "favorites_editor_"


def invalidate_editor_state() -> None:
    """
    Сбросить delta-state всех data_editor-ов, привязанных к избранному.

    Streamlit рекомендует сбрасывать виджет через ``del
    st.session_state[key]``: на следующем rerun виджет пересоздаётся
    из свежего input-DataFrame, накопленные правки игнорируются. Это
    то, что нужно после save-а ``favorites.json`` или после внешнего
    toggle с другой страницы.
    """
    for key in list(st.session_state.keys()):
        if isinstance(key, str) and key.startswith(
            (SCREENER_EDITOR_PREFIX, FAVORITES_EDITOR_PREFIX)
        ):
            del st.session_state[key]


# ──────────────────────────────────────────────
#  Bond detail components
# ──────────────────────────────────────────────


def render_external_links(bond: BondRecord) -> None:
    """Render a row of links to external bond pages (T-Bank catalog, …).

    The T-Bank catalog page is addressed by ISIN; if the bond has no ISIN,
    the function renders nothing (the link target would be invalid).
    """
    if not bond.isin:
        return
    tbank_url = _TBANK_BOND_URL_TEMPLATE.format(isin=bond.isin)
    st.markdown(f":material/open_in_new: [Открыть в Т-Банк]({tbank_url})")


def render_favorite_toggle_button(bond: BondRecord, *, key: str) -> bool:
    """
    Кнопка-переключатель «в избранном» для страницы деталей бумаги.

    Streamlit ``st.button`` поддерживает Material-иконки в label через
    синтаксис ``:material/<name>:``. На каждый прогон страницы рендерим
    кнопку с актуальным текстом — после клика вызывающий код должен
    переключить состояние в ``data.favorites`` и сделать ``st.rerun()``.

    Returns:
        ``True`` если кнопка была нажата на этом прогоне, иначе ``False``.
    """
    if bond.is_favorite:
        label = ":material/star: Убрать из избранного"
        button_type = "secondary"
        help_text = "Удалить эту бумагу из списка избранного"
    else:
        label = ":material/star_outline: В избранное"
        button_type = "secondary"
        help_text = "Сохранить эту бумагу в личный список избранного"
    return st.button(label, key=key, type=button_type, help=help_text)


def render_key_metrics(bond: BondRecord) -> None:
    """Render four key metric cards for a bond."""
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric(
            "YTM нетто",
            f"{bond.ytm_net:.2f}%" if bond.ytm_net is not None else "—",
            help="Доходность к погашению после НДФЛ (ставка настраивается в сайдбаре)",
        )
    with c2:
        st.metric(
            "YTM брутто",
            f"{bond.ytm:.2f}%" if bond.ytm is not None else "—",
            help="Доходность к погашению до уплаты НДФЛ",
        )
    with c3:
        st.metric(
            "Дней до даты",
            str(bond.days_to_maturity or "—"),
            help="Дней до ближайшей даты: погашение или пут-оферта",
        )
    with c4:
        st.metric(
            "Скор",
            f"{bond.score:.1f} / 100" if bond.score is not None else "—",
            help="Совокупный скор: YTM×40% + Риск×40% + Ликвидность×20%",
        )


def render_price_block(bond: BondRecord) -> None:
    """Render price, НКД, and lot cost info."""
    c1, c2, c3 = st.columns(3)
    with c1:
        clean = bond.clean_price_rub
        clean_str = (
            f"{bond.last_price:.2f}%"
            if clean is not None and bond.last_price is not None
            else MISSING_VALUE
        )
        st.metric(
            "Чистая цена",
            clean_str,
            help="% от номинала / рублей за 1 облигацию",
            delta_description=format_rub(clean),
        )
    with c2:
        st.metric(
            "НКД",
            format_rub(bond.accrued_interest),
            help="Накопленный купонный доход — уплачивается при покупке и возвращается с первым купоном",
        )
    with c3:
        lot_cost = bond.price_per_lot_rub
        lot_str = f"{format_rub(lot_cost, decimals=0)}" if lot_cost is not None else MISSING_VALUE
        lot_description = f"(лот = {format_number(bond.lot_size, decimals=0)} шт.)"
        st.metric(
            "Стоимость лота",
            lot_str,
            help="Грязная цена × лотность (минимальная сумма покупки)",
            delta_description=lot_description,
        )


def render_warnings(bond: BondRecord) -> None:
    """Show risk warning callouts for a bond."""
    warnings = bond.warnings_list()
    if not warnings:
        st.success("Существенных структурных рисков не обнаружено")
        return
    for w in warnings:
        st.warning(w)


def render_score_breakdown(bond: BondRecord) -> None:
    """Show score components as a small table."""
    rows = [
        ("YTM-скор (вес 40%)", bond.ytm_score),
        ("Риск-скор (вес 40%)", bond.risk_score),
        ("Ликвидность-скор (вес 20%)", bond.liquidity_score),
        ("Итоговый скор", bond.score),
    ]
    data = {
        "Компонент": [r[0] for r in rows],
        "Значение": [f"{r[1]:.1f}" if r[1] is not None else "—" for r in rows],
    }
    st.dataframe(pd.DataFrame(data), hide_index=True, use_container_width=True)


_BOND_INFO_TABLE_CSS: str = """
<style>
.bm-info-table {
    width: 100%;
    border-collapse: collapse;
    margin: 0;
    font-size: 0.92rem;
}
.bm-info-table th, .bm-info-table td {
    text-align: left;
    padding: 6px 12px;
    /* Neutral border that reads on both light and dark themes. */
    border-bottom: 1px solid rgba(127, 127, 127, 0.18);
    vertical-align: middle;
}
.bm-info-table th {
    font-weight: 600;
    opacity: 0.7;
}
.bm-info-table td:first-child {
    width: 38%;
    white-space: nowrap;
}
.bm-info-table .bm-help {
    /* Small unobtrusive info icon next to the parameter name. */
    display: inline-block;
    margin-left: 6px;
    width: 16px;
    height: 16px;
    line-height: 16px;
    text-align: center;
    font-size: 13px;
    color: currentColor;
    opacity: 0.45;
    cursor: help;
    transition: opacity 0.15s ease;
    user-select: none;
}
.bm-info-table .bm-help:hover {
    opacity: 1;
}
</style>
"""


def render_bond_info_table(bond: BondRecord) -> None:
    """Render the full bond parameter table with per-row tooltip icons.

    ``st.dataframe`` doesn't support per-cell tooltips, so we emit a
    plain HTML table via ``st.markdown(unsafe_allow_html=True)``. Each
    parameter has a small ``ⓘ`` icon next to its name with a native
    browser tooltip (``title`` attribute) carrying a one-sentence
    glossary entry — most useful for terms newcomers stumble over
    (put-offer vs call-offer, amortization vs maturity, etc.). The CSS
    uses ``currentColor`` + ``opacity`` so the styling reads correctly
    on both light and dark Streamlit themes.
    """
    coupon_label = COUPON_TYPE_LABELS.get(bond.coupon_type, "Неизвестен")
    risk_label = RISK_LEVEL_LABELS.get(bond.risk_level, "—")

    params: list[tuple[str, str, str]] = [
        (
            "ISIN",
            bond.isin,
            "Международный идентификационный код ценной бумаги (12 символов)",
        ),
        (
            "Тикер (SECID)",
            bond.secid,
            "Биржевой тикер MOEX — короткий код, используется в торговых системах",
        ),
        (
            "FIGI",
            bond.figi or MISSING_VALUE,
            "Глобальный идентификатор инструмента, нужен для запросов в T-Invest API",
        ),
        (
            "Номинал",
            format_rub(bond.face_value, decimals=0),
            "Сумма, которую эмитент вернёт держателю облигации в дату погашения",
        ),
        (
            "Дата погашения",
            bond.maturity_date.isoformat() if bond.maturity_date else MISSING_VALUE,
            "Когда эмитент обязан вернуть номинал. После этой даты облигации больше нет",
        ),
        (
            "Дата пут-оферты",
            bond.offer_date.isoformat() if bond.offer_date else MISSING_VALUE,
            (
                "Дата исполнения: эмитент выкупает бумаги у тех, кто подал заявку. "
                "YTM до этой даты считается MOEX именно к оферте"
            ),
        ),
        (
            "Окно подачи (пут)",
            (
                f"{bond.offer_submission_start.isoformat()} — "
                f"{bond.offer_submission_end.isoformat()}"
                if bond.offer_submission_start and bond.offer_submission_end
                else (
                    f"до {bond.offer_submission_end.isoformat()}"
                    if bond.offer_submission_end
                    else MISSING_VALUE
                )
            ),
            "Период, когда можно подать заявку на предъявление (обычно через чат брокера)",
        ),
        (
            "Цена пут-оферты",
            f"{bond.offer_price_pct:.2f}% номинала" if bond.offer_price_pct else MISSING_VALUE,
            "По какой цене эмитент выкупит бумагу при предъявлении — часто ниже 100%",
        ),
        (
            "Дата колл-оферты",
            bond.call_date.isoformat() if bond.call_date else MISSING_VALUE,
            (
                "Право ЭМИТЕНТА досрочно выкупить облигацию у инвесторов по 100% "
                "от номинала. При падении ставок эмитент часто пользуется этим "
                "правом, поэтому реальный срок бумаги может оказаться короче"
            ),
        ),
        (
            "Купонная ставка",
            f"{bond.coupon_rate:.2f}%" if bond.coupon_rate else MISSING_VALUE,
            "Годовая ставка купона в процентах от номинала",
        ),
        (
            "Тип купона",
            coupon_label,
            (
                "Фиксированный — известен заранее; Плавающий — привязан к КС ЦБ или "
                "RUONIA, меняется вслед за рынком; Переменный — устанавливается "
                "эмитентом перед каждым купонным периодом"
            ),
        ),
        (
            "Период купона, дней",
            str(bond.coupon_period_days or MISSING_VALUE),
            "Сколько дней между выплатами купонов (91 — ежеквартально, 182 — раз в полгода)",
        ),
        (
            "След. купон",
            bond.next_coupon_date.isoformat() if bond.next_coupon_date else MISSING_VALUE,
            "Дата ближайшей купонной выплаты",
        ),
        (
            "Размер купона",
            format_rub(bond.coupon_value),
            "Размер следующего купонного платежа за 1 облигацию",
        ),
        (
            "Дюрация, дней",
            f"{bond.duration_days:.0f}" if bond.duration_days else MISSING_VALUE,
            (
                "Средневзвешенный срок возврата вложений (Macaulay) — мера "
                "процентного риска. Чем меньше дюрация, тем слабее цена реагирует "
                "на движение ключевой ставки"
            ),
        ),
        (
            "Кредитный рейтинг",
            bond.credit_rating or MISSING_VALUE,
            (
                "Оценка платёжеспособности эмитента по национальной шкале "
                "(Эксперт РА / АКРА / НКР). Шкала: ruAAA > ruAA > ruA > ruBBB > "
                "ruBB > ruB > ruCCC > ruD"
            ),
        ),
        (
            "Уровень риска (T-Invest)",
            risk_label,
            "Категория риска от T-Invest: Низкий / Умеренный / Высокий / Неизвестен",
        ),
        (
            "Амортизация",
            "Да" if bond.amortization_flag else "Нет",
            (
                "Эмитент возвращает номинал ЧАСТЯМИ по графику, а не одной "
                "выплатой в дату погашения. Эффективная доходность обычно ниже "
                "купонной из-за более раннего возврата тела"
            ),
        ),
        (
            "Субординирован",
            "Да" if bond.subordinated_flag else "Нет",
            (
                "При банкротстве эмитента выплачивается ПОСЛЕ всех остальных "
                "кредиторов — повышенный риск потерь"
            ),
        ),
        (
            "Только квалинвесторы",
            "Да" if bond.for_qual_investor_flag else "Нет",
            "Покупать могут только инвесторы со статусом квалифицированного",
        ),
        (
            "Дефолт",
            "Да" if bond.has_default else "Нет",
            (
                "MOEX HASDEFAULT: эмитент формально допустил дефолт по обязательствам "
                "(пропущена выплата купона/номинала, грейс-период истёк)"
            ),
        ),
        (
            "Технический дефолт",
            "Да" if bond.has_technical_default else "Нет",
            (
                "MOEX HASTECHNICALDEFAULT: эмитент пропустил выплату, но грейс-период "
                "ещё не истёк — состояние может разрешиться без перехода в полный дефолт"
            ),
        ),
        (
            "Обогащён из T-Invest",
            "Да" if bond.tinvest_enriched else "Нет",
            "Признак того, что данные дополнены через T-Invest API (рейтинг, флаги риска)",
        ),
        (
            "Объём торгов (день)",
            f"{format_number((bond.volume_rub or 0) / 1_000_000, decimals=1)} млн ₽",
            "Суммарный объём сделок по бумаге за текущий торговый день на MOEX",
        ),
    ]

    rows_html: list[str] = []
    for name, value, descr in params:
        safe_name = html.escape(name)
        safe_value = html.escape(value if value not in (None, "") else MISSING_VALUE)
        # ``title`` is an HTML attribute, so the description has to be
        # escaped with ``quote=True`` to neutralise any embedded quotes.
        safe_descr = html.escape(descr, quote=True)
        rows_html.append(
            "<tr>"
            f'<td>{safe_name}<span class="bm-help" title="{safe_descr}">ⓘ</span></td>'
            f"<td>{safe_value}</td>"
            "</tr>"
        )

    table_html = (
        '<table class="bm-info-table">'
        "<thead><tr><th>Параметр</th><th>Значение</th></tr></thead>"
        "<tbody>" + "".join(rows_html) + "</tbody>"
        "</table>"
    )
    st.markdown(_BOND_INFO_TABLE_CSS + table_html, unsafe_allow_html=True)
