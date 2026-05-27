"""
Streamlit UI для модуля «Портфель».

Содержит только функции рендеринга и обработчики действий пользователя.
Получение данных (универс облигаций, ставка ЦБ, ставка НДФЛ) и кэширование
происходит в :mod:`app`; этот модуль принимает их параметрами.

Архитектурный контракт:

* Все мутации портфеля идут через :mod:`data.portfolios` (CRUD-функции
  атомарно сохраняют состояние) — в текущем модуле нет прямой записи в
  файл.
* Любая операция, меняющая состояние портфеля (создание/удаление/
  переименование/решение по оферте/замена слота), завершается явным
  ``st.rerun()`` для немедленной отрисовки нового состояния.
* Нет прямых обращений к T-Invest или MOEX — модуль безразличен к
  источнику данных.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from core.bond_model import BondRecord
from core.formatting import format_number, format_rub
from core.portfolio_model import (
    RISK_PROFILE_LABELS,
    Portfolio,
    PositionSourceType,
    PutOfferDecision,
    ReinvestmentSlot,
    ReinvestmentTriggerReason,
    RiskProfile,
)
from core.portfolio_planner import (
    PUT_OFFER_REMINDER_DAYS,
    REINVESTMENT_GAP_DAYS,
    CashflowEvent,
    PortfolioPlan,
    auto_compose,
    build_plan,
    position_from_bond,
    risk_profile_filter,
    validate_replacement_bond,
)
from core.scorer import score_bonds_for_profile
from data.portfolios import (
    create_portfolio,
    delete_portfolio,
    rename_portfolio,
    update_portfolio,
)
from ui.components import DETAIL_QUERY_PARAM

# ── Константы UI ─────────────────────────────────────────────────────────────

_DEFAULT_INITIAL_AMOUNT_RUB: float = 100_000.0
_DEFAULT_HORIZON_MONTHS: int = 12

_POSITION_SOURCE_LABELS: dict[PositionSourceType, str] = {
    PositionSourceType.INITIAL: "Стартовая",
    PositionSourceType.REINVEST_MATURITY: "Реинвест. (погашение)",
    PositionSourceType.REINVEST_PUT_OFFER: "Реинвест. (пут-оферта)",
    PositionSourceType.REINVEST_COUPON_CASH: "Реинвест. (купоны)",
}

_TRIGGER_REASON_LABELS: dict[ReinvestmentTriggerReason, str] = {
    ReinvestmentTriggerReason.MATURITY: "Погашение",
    ReinvestmentTriggerReason.PUT_OFFER: "Пут-оферта",
    ReinvestmentTriggerReason.COUPON_CASH: "Накопл. купонный кэш",
}

_EVENT_KIND_LABELS: dict[str, str] = {
    "purchase": "Покупка",
    "coupon": "Купон",
    "maturity": "Погашение",
    "put_offer": "Пут-оферта",
}


# ── Точка входа из app.py ────────────────────────────────────────────────────


def render_portfolio_tab(
    *,
    universe: Sequence[BondRecord],
    key_rate: float,
    tax_rate: float,
    today: date,
) -> None:
    """Точка входа во вкладку «Портфель».

    Загружает портфели из :mod:`data.portfolios`, рисует селектор и весь
    остальной UI выбранного портфеля. Параметры из сайдбара пробрасываются
    в планировщик «как есть» — портфель строится с теми же значениями
    ключевой ставки и НДФЛ, что и скринер.
    """
    from data.portfolios import load_portfolios

    portfolios = load_portfolios()
    portfolio = render_portfolio_selector(portfolios)

    if portfolio is None:
        st.info(
            "Создайте первый портфель: задайте сумму, горизонт и риск-профиль. "
            "Можно добавлять бумаги вручную или собрать состав автоматически."
        )
        _render_create_form()
        return

    st.divider()
    settings_changed = render_portfolio_settings(portfolio)
    if settings_changed:
        update_portfolio(portfolio)
        st.rerun()

    st.divider()

    if not universe:
        st.warning(
            "Универс MOEX пуст. Откройте вкладку «Скринер» с менее жёсткими "
            "фильтрами и вернитесь на «Портфель»."
        )
        return

    plan = build_plan(
        portfolio,
        universe,
        today=today,
        key_rate=key_rate,
        tax_rate=tax_rate,
    )

    render_portfolio_summary(plan)

    st.divider()
    render_put_offer_reminders(portfolio, plan)

    st.divider()
    render_positions_table(portfolio, universe)

    st.divider()
    _render_manual_add_section(portfolio, universe, today, key_rate=key_rate, tax_rate=tax_rate)

    st.divider()
    render_reinvestment_slots(portfolio, plan, universe)

    st.divider()
    render_timeline(plan)

    if plan.notes:
        with st.expander(f"Замечания планировщика ({len(plan.notes)})", expanded=False):
            for note in plan.notes:
                st.caption(f"• {note}")

    st.divider()
    render_trading_stub_section()


# ── Селектор / CRUD портфелей ────────────────────────────────────────────────


def render_portfolio_selector(portfolios: list[Portfolio]) -> Portfolio | None:
    """Выпадающий список портфелей + кнопки управления.

    Returns:
        Текущий выбранный ``Portfolio`` или ``None``, если список пуст.
        Selected id хранится в ``st.session_state`` под ключом
        ``portfolio_selected_id`` — пережив rerun.
    """
    st.subheader("Портфели")

    if not portfolios:
        return None

    portfolio_by_id = {p.id: p for p in portfolios}
    saved_id = st.session_state.get("portfolio_selected_id")
    if saved_id not in portfolio_by_id:
        saved_id = portfolios[0].id
        st.session_state["portfolio_selected_id"] = saved_id

    col_select, col_create, col_rename, col_delete = st.columns([4, 1, 1, 1])
    with col_select:
        selected_id = st.selectbox(
            "Активный портфель",
            options=[p.id for p in portfolios],
            format_func=lambda pid: portfolio_by_id[pid].name,
            index=[p.id for p in portfolios].index(saved_id),
            label_visibility="collapsed",
            key="portfolio_selector",
        )
        st.session_state["portfolio_selected_id"] = selected_id

    selected = portfolio_by_id[selected_id]

    with col_create:
        if st.button("Новый", use_container_width=True, key="portfolio_btn_new"):
            st.session_state["portfolio_show_create"] = True
    with col_rename:
        if st.button("Имя", use_container_width=True, key="portfolio_btn_rename"):
            st.session_state["portfolio_show_rename"] = True
    with col_delete:
        if st.button("Удал.", use_container_width=True, key="portfolio_btn_delete"):
            st.session_state["portfolio_confirm_delete"] = True

    if st.session_state.get("portfolio_show_create"):
        _render_create_form()
    if st.session_state.get("portfolio_show_rename"):
        _render_rename_form(selected)
    if st.session_state.get("portfolio_confirm_delete"):
        _render_delete_confirm(selected)

    return selected


def _render_create_form() -> None:
    """Форма создания нового портфеля."""
    with st.form("portfolio_create_form", clear_on_submit=True):
        st.markdown("**Создать новый портфель**")
        name = st.text_input("Название", value="Новый портфель")
        col_amount, col_horizon, col_profile = st.columns(3)
        with col_amount:
            initial_amount = st.number_input(
                "Стартовая сумма, ₽",
                min_value=1_000.0,
                max_value=1_000_000_000.0,
                value=_DEFAULT_INITIAL_AMOUNT_RUB,
                step=10_000.0,
            )
        with col_horizon:
            horizon_months = st.number_input(
                "Горизонт, мес.",
                min_value=1,
                max_value=120,
                value=_DEFAULT_HORIZON_MONTHS,
                step=1,
            )
        with col_profile:
            profile_value = st.selectbox(
                "Риск-профиль",
                options=[p.value for p in RiskProfile],
                format_func=lambda v: RISK_PROFILE_LABELS[RiskProfile(v)],
            )

        col_submit, col_cancel = st.columns([1, 1])
        with col_submit:
            submitted = st.form_submit_button("Создать", type="primary")
        with col_cancel:
            cancelled = st.form_submit_button("Отмена")

    if submitted:
        horizon_date = date.today() + timedelta(days=int(horizon_months) * 30)
        portfolio = create_portfolio(
            name=name,
            initial_amount_rub=float(initial_amount),
            horizon_date=horizon_date,
            risk_profile=RiskProfile(profile_value),
        )
        st.session_state["portfolio_selected_id"] = portfolio.id
        st.session_state["portfolio_show_create"] = False
        st.rerun()
    elif cancelled:
        st.session_state["portfolio_show_create"] = False
        st.rerun()


def _render_rename_form(portfolio: Portfolio) -> None:
    with st.form("portfolio_rename_form"):
        st.markdown(f"**Переименовать «{portfolio.name}»**")
        new_name = st.text_input("Новое название", value=portfolio.name)
        col_submit, col_cancel = st.columns([1, 1])
        with col_submit:
            submitted = st.form_submit_button("Сохранить", type="primary")
        with col_cancel:
            cancelled = st.form_submit_button("Отмена")
    if submitted:
        rename_portfolio(portfolio.id, new_name)
        st.session_state["portfolio_show_rename"] = False
        st.rerun()
    elif cancelled:
        st.session_state["portfolio_show_rename"] = False
        st.rerun()


def _render_delete_confirm(portfolio: Portfolio) -> None:
    st.warning(
        f"Удалить портфель «{portfolio.name}» безвозвратно? "
        "Все позиции и слоты реинвестиций будут потеряны."
    )
    col_yes, col_no = st.columns([1, 1])
    with col_yes:
        if st.button("Да, удалить", type="primary", key="portfolio_confirm_yes"):
            delete_portfolio(portfolio.id)
            st.session_state.pop("portfolio_selected_id", None)
            st.session_state["portfolio_confirm_delete"] = False
            st.rerun()
    with col_no:
        if st.button("Отмена", key="portfolio_confirm_no"):
            st.session_state["portfolio_confirm_delete"] = False
            st.rerun()


# ── Параметры и автосостав ───────────────────────────────────────────────────


def render_portfolio_settings(portfolio: Portfolio) -> bool:
    """Поля «сумма / горизонт / риск-профиль» + кнопка автосостава.

    Returns:
        ``True``, если пользователь изменил значение какого-то поля
        (вызывающему коду нужно сохранить портфель и сделать rerun).
    """
    st.subheader("Параметры портфеля")

    changed = False

    col_amount, col_horizon, col_profile = st.columns(3)
    with col_amount:
        new_amount = st.number_input(
            "Стартовая сумма, ₽",
            min_value=1_000.0,
            max_value=1_000_000_000.0,
            value=float(portfolio.initial_amount_rub),
            step=10_000.0,
            key=f"portfolio_amount_{portfolio.id}",
            help=(
                "Бюджет, который распределяется по бумагам при автосоставе. "
                "Изменение не пересчитывает уже купленные позиции."
            ),
        )
        if abs(new_amount - portfolio.initial_amount_rub) > 1e-6:
            portfolio.initial_amount_rub = float(new_amount)
            changed = True

    with col_horizon:
        new_horizon = st.date_input(
            "Горизонт планирования",
            value=portfolio.horizon_date,
            min_value=date.today() + timedelta(days=1),
            max_value=date.today() + timedelta(days=3650),
            key=f"portfolio_horizon_{portfolio.id}",
            help=(
                "Дата, до которой строятся цепочки реинвестиций. "
                "Бумаги, погашаемые после неё, не подбираются ни в "
                "автосостав, ни в слоты замен."
            ),
        )
        if isinstance(new_horizon, date) and new_horizon != portfolio.horizon_date:
            portfolio.horizon_date = new_horizon
            changed = True

    with col_profile:
        profile_options = [p.value for p in RiskProfile]
        current_idx = profile_options.index(portfolio.risk_profile.value)
        new_profile_value = st.selectbox(
            "Риск-профиль",
            options=profile_options,
            index=current_idx,
            format_func=lambda v: RISK_PROFILE_LABELS[RiskProfile(v)],
            key=f"portfolio_profile_{portfolio.id}",
            help=(
                "Нормальный — рейтинг ≥ ruA-, без субординации, без HIGH-риска "
                "T-Invest, скоринг 30/50/20 (упор на качество). "
                "Агрессивный — рейтинг ≥ ruBB-, разрешены HIGH-риск, амортизация, "
                "колл-оферта; скоринг 55/25/20 (упор на доходность)."
            ),
        )
        if new_profile_value != portfolio.risk_profile.value:
            portfolio.risk_profile = RiskProfile(new_profile_value)
            changed = True

    return changed


def _render_manual_add_section(
    portfolio: Portfolio,
    universe: Sequence[BondRecord],
    today: date,
    *,
    key_rate: float,
    tax_rate: float,
) -> None:
    """Кнопка «Автосоставить» + форма ручного добавления бумаги."""
    st.subheader("Состав портфеля")
    col_auto, col_clear = st.columns([1, 1])
    with col_auto:
        if st.button(
            "Автосоставить по риск-профилю",
            type="primary",
            use_container_width=True,
            help=(
                "Распределяет стартовую сумму по топ-бумагам выбранного профиля "
                "(не более 25% бюджета в одну бумагу, до 10 позиций). Заменяет "
                "текущий состав, но сохраняет горизонт и профиль."
            ),
        ):
            positions, leftover, notes = auto_compose(
                initial_amount=portfolio.initial_amount_rub,
                universe=universe,
                profile=portfolio.risk_profile,
                horizon_date=portfolio.horizon_date,
                today=today,
                key_rate=key_rate,
                tax_rate=tax_rate,
            )
            portfolio.positions = positions
            portfolio.cash_balance_rub = leftover
            portfolio.slots = []
            update_portfolio(portfolio)
            for note in notes:
                st.toast(note)
            st.rerun()
    with col_clear:
        if st.button(
            "Очистить состав",
            use_container_width=True,
            help="Удаляет все позиции и слоты, возвращает кэш-баланс к стартовой сумме.",
        ):
            portfolio.positions = []
            portfolio.slots = []
            portfolio.cash_balance_rub = 0.0
            update_portfolio(portfolio)
            st.rerun()

    with st.expander("Добавить бумагу вручную", expanded=False):
        _render_manual_add_form(portfolio, universe, today)


def _render_manual_add_form(
    portfolio: Portfolio,
    universe: Sequence[BondRecord],
    today: date,
) -> None:
    """Форма ручного добавления одной позиции в портфель."""
    if not universe:
        st.info("Универс пуст — добавлять нечего.")
        return

    universe_by_isin = {b.isin: b for b in universe}
    options = [b.isin for b in universe]
    selected_isin = st.selectbox(
        "Бумага",
        options=options,
        format_func=lambda isin: f"{universe_by_isin[isin].secid} — {universe_by_isin[isin].name}",
        key=f"portfolio_manual_isin_{portfolio.id}",
    )
    bond = universe_by_isin[selected_isin]
    lot_cost = bond.price_per_lot_rub or 0.0

    col_lots, col_info, col_btn = st.columns([1, 2, 1])
    with col_lots:
        lots = st.number_input(
            "Лотов",
            min_value=1,
            max_value=10_000,
            value=1,
            step=1,
            key=f"portfolio_manual_lots_{portfolio.id}",
        )
    with col_info:
        st.metric(
            "Стоимость лота",
            format_rub(lot_cost) if lot_cost > 0 else "—",
            delta_description=f"за {format_number(int(lots) * lot_cost, decimals=0)} ₽ всего",
        )
    with col_btn:
        if st.button("Добавить", type="primary", key=f"portfolio_manual_add_{portfolio.id}"):
            position = position_from_bond(
                bond,
                lots=int(lots),
                purchase_date=today,
                source=PositionSourceType.INITIAL,
            )
            portfolio.positions.append(position)
            update_portfolio(portfolio)
            st.rerun()


# ── Сводка / итог ────────────────────────────────────────────────────────────


def render_portfolio_summary(plan: PortfolioPlan) -> None:
    """Карточки с итоговыми цифрами портфеля.

    Главные цифры:

    * **Эффективная годовая доходность** — реальный annualized return
      портфеля за горизонт (отвечает на вопрос «как у депозита»).
      Считается как ``(final_value / initial)^(365/days) − 1``.
    * **Итоговая прибыль** — разница между итоговой стоимостью портфеля
      (кэш + удерживаемые бумаги) и стартовой суммой.

    Подсветка YTM:

    * **YTM текущих позиций** — годовая YTM нетто только initial-позиций,
      к их собственному погашению. НЕ описывает доходность за горизонт.
    * **YTM всех позиций плана** — то же, но включая phantom-позиции
      реинвест-цепочек. Если она ниже YTM текущих позиций — реинвестиции
      «разбавляют» доходность (в notes плана появится явный warning).
    """
    st.subheader("Итоги по портфелю")
    portfolio = plan.portfolio

    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric(
        "Стартовая сумма",
        format_rub(portfolio.initial_amount_rub, decimals=0),
        help="Сумма, заданная пользователем при создании портфеля.",
    )
    col_b.metric(
        "Итоговая стоимость",
        format_rub(plan.final_portfolio_value_rub, decimals=0),
        help=("Кэш + удерживаемые бумаги = «сколько денег в портфеле всего» на дату горизонта."),
    )
    col_c.metric(
        "Итоговая прибыль",
        format_rub(plan.total_net_profit_with_held_rub, decimals=0),
        delta=(
            f"{plan.total_net_profit_with_held_rub / portfolio.initial_amount_rub * 100:+.1f}%"
            if portfolio.initial_amount_rub > 0
            else None
        ),
        help=(
            "Итоговая стоимость − стартовая сумма. Учитывает и кэш, и "
            "оценочную стоимость недогашенных бумаг."
        ),
    )
    if plan.effective_annual_return_pct is not None:
        col_d.metric(
            "Эффективная годовая доходность",
            f"{plan.effective_annual_return_pct:+.2f}%",
            help=(
                "Реальная annualized доходность портфеля за горизонт: "
                "(итоговая стоимость / стартовая сумма) ^ (365 / дней горизонта) − 1. "
                "Это самая корректная цифра для сравнения с депозитом или "
                "ключевой ставкой. Учитывает все купоны, налоги, "
                "реинвестиции и settlement-gaps."
            ),
        )
    else:
        col_d.metric("Эффективная годовая доходность", "—")

    col_e, col_f, col_g, col_h = st.columns(4)
    col_e.metric(
        "Кэш на горизонте",
        format_rub(plan.final_cash_balance_rub, decimals=0),
        help=(
            "Деньги, которые «материализовались» к дате горизонта: "
            "погашения + купоны + последние возвраты номинала, минус все "
            "будущие реинвестиционные покупки."
        ),
    )
    col_f.metric(
        "Удерживаемые бумаги",
        format_rub(plan.held_positions_value_rub, decimals=0),
        help=(
            "Оценочная стоимость бумаг, которые ещё не погасились к "
            "горизонту (maturity > horizon). Стоимость берётся как "
            "live-цена × количество, при отсутствии цены — номинал."
        ),
    )
    col_g.metric(
        "Купонный доход (нетто)",
        format_rub(plan.total_coupon_net_rub, decimals=0),
        help="Накопленный купонный доход за весь горизонт после НДФЛ.",
    )
    col_h.metric(
        "Уплачено НДФЛ",
        format_rub(plan.total_tax_rub, decimals=0),
        help=(
            "Сумма НДФЛ по двум видам дохода:\n\n"
            "• **Купоны**: налог = купон_брутто × ставка. "
            "Пример при ставке 18%: купон 100 ₽ брутто → вы получаете 82 ₽, "
            "платите 18 ₽. Поэтому налог = чистые_купоны × 18% / 82% ≈ 21,95% "
            "от чистого дохода, а не 18% — 18% берётся от брутто.\n\n"
            "• **Курсовая разница**: если бумага куплена ниже номинала, "
            "при погашении налог = (номинал − цена_покупки) × ставка. "
            "Возврат самого номинала налогом не облагается.\n\n"
            "Итого: налог / (налог + чистая_прибыль) ≠ ставка_НДФЛ, "
            "так как ставка применяется к брутто-доходу."
        ),
    )

    col_i, col_j, col_k, col_l = st.columns(4)
    col_i.metric(
        "Вложено всего",
        format_rub(plan.total_invested_rub, decimals=0),
        help=(
            "Суммарная стоимость всех покупок, включая phantom-позиции "
            "реинвест-цепочек. Может превышать стартовую сумму, если "
            "деньги «прокручиваются» несколько раз."
        ),
    )
    col_j.metric(
        "Возврат номинала (все цепочки)",
        format_rub(plan.total_redemption_rub, decimals=0),
        help=(
            "Сумма всех выплат номинала по всем бумагам, включая "
            "phantom-позиции реинвест-цепочек. Каждая maturity → "
            "следующая reinvest-покупка, поэтому при цепочках эта цифра "
            "растёт пропорционально числу циклов (а НЕ остаётся равной "
            "стартовой сумме)."
        ),
    )
    if plan.weighted_ytm_net_pct is not None:
        col_k.metric(
            "YTM текущих позиций",
            f"{plan.weighted_ytm_net_pct:.2f}%",
            help=(
                "Средневзвешенная (по сумме покупки) YTM нетто ТОЛЬКО "
                "текущих initial-позиций — к их собственному погашению. "
                "Это ГОДОВАЯ доходность; реальная прибыль = "
                "purchase × ((1 + YTM)^(days / 365) − 1). "
                "НЕ описывает доходность портфеля за горизонт, если "
                "присутствуют реинвестиции."
            ),
        )
    else:
        col_k.metric("YTM текущих позиций", "—")
    if plan.weighted_ytm_net_full_pct is not None:
        delta_full = (
            f"{plan.weighted_ytm_net_full_pct - plan.weighted_ytm_net_pct:+.2f} п.п."
            if plan.weighted_ytm_net_pct is not None
            else None
        )
        col_l.metric(
            "YTM всех позиций плана",
            f"{plan.weighted_ytm_net_full_pct:.2f}%",
            delta=delta_full,
            delta_color="normal",
            help=(
                "Средневзвешенная YTM нетто по ВСЕМ позициям плана, "
                "включая phantom-ы реинвест-цепочек. Если значительно "
                "ниже «YTM текущих позиций» — реинвестиции «разбавляют» "
                "доходность (короткие бумаги на дату реинвеста имеют "
                "более низкую YTM, чем твои стартовые). В notes плана "
                "появится явный warning, если разбавление > 30%."
            ),
        )
    else:
        col_l.metric("YTM всех позиций плана", "—")

    if plan.held_positions:
        with st.expander(
            f"Удерживаемые бумаги на горизонте ({len(plan.held_positions)})",
            expanded=False,
        ):
            for held in plan.held_positions:
                pos = held.position
                end = pos.maturity_date.isoformat() if pos.maturity_date else "—"
                st.markdown(
                    f"**{pos.name}** ({pos.secid}) · "
                    f"{pos.bonds_count} облиг. · "
                    f"погашение {end} · "
                    f"оценка: {format_rub(held.estimated_value_rub, decimals=0)} "
                    f"({held.valuation_source})"
                )


# ── Напоминания о пут-офертах ────────────────────────────────────────────────


def render_put_offer_reminders(portfolio: Portfolio, plan: PortfolioPlan) -> None:
    """Блок напоминаний о ближайших пут-офертах с выбором решения."""
    st.subheader("Пут-оферты — требуют решения")

    if not plan.upcoming_put_offers:
        st.success(f"В ближайшие {PUT_OFFER_REMINDER_DAYS} дней пут-оферт по позициям нет.")
        return

    st.caption(
        f"Бумаги с пут-офертой в ближайшие {PUT_OFFER_REMINDER_DAYS} дней. "
        "Заявку на предъявление нужно подать в окно между датами «начало» и "
        "«конец подачи» (через чат брокера). «Предъявить» — выкуп по цене "
        "оферты (может быть ниже 100% номинала) и реинвест через 2 дня. "
        "«Держать» — до погашения."
    )

    for upcoming in plan.upcoming_put_offers:
        position = upcoming.position
        days_until = upcoming.days_until
        col_info, col_yes, col_no = st.columns([4, 1, 1])
        with col_info:
            window_parts: list[str] = []
            if upcoming.submission_start:
                window_parts.append(f"с `{upcoming.submission_start.isoformat()}`")
            if upcoming.submission_end:
                window_parts.append(f"до `{upcoming.submission_end.isoformat()}`")
            window_str = " ".join(window_parts) if window_parts else "—"
            price_str = (
                f"{upcoming.offer_price_pct:.0f}% номинала"
                if upcoming.offer_price_pct is not None
                else "100% номинала (нет данных MOEX)"
            )
            st.markdown(
                f"**{position.name}** — исполнение оферты "
                f"`{position.offer_date.isoformat() if position.offer_date else '—'}` "
                f"(через **{days_until}** дн.)"
            )
            st.caption(f"Подача заявки: {window_str} · цена выкупа: {price_str}")
            if not upcoming.can_exercise and upcoming.submission_end:
                if date.today() > upcoming.submission_end:
                    st.error(
                        f"Окно подачи закрыто {upcoming.submission_end.isoformat()}. "
                        "Предъявить уже нельзя — держите до погашения."
                    )
                elif upcoming.submission_start and date.today() < upcoming.submission_start:
                    st.info(f"Окно откроется {upcoming.submission_start.isoformat()}.")
        with col_yes:
            if st.button(
                "Предъявить",
                key=f"putoffer_exercise_{portfolio.id}_{position.isin}",
                type="primary",
                use_container_width=True,
                disabled=not upcoming.can_exercise,
            ):
                _set_put_offer_decision(portfolio, position.isin, PutOfferDecision.EXERCISE)
                st.rerun()
        with col_no:
            if st.button(
                "Держать",
                key=f"putoffer_hold_{portfolio.id}_{position.isin}",
                use_container_width=True,
            ):
                _set_put_offer_decision(portfolio, position.isin, PutOfferDecision.HOLD)
                st.rerun()


def _set_put_offer_decision(
    portfolio: Portfolio,
    position_isin: str,
    decision: PutOfferDecision,
) -> None:
    for position in portfolio.positions:
        if position.isin == position_isin:
            position.put_offer_decision = decision
            break
    # При смене решения — сбросим связанные слоты, чтобы они пересчитались
    # с учётом новой даты ``end_date``.
    portfolio.slots = [s for s in portfolio.slots if s.source_position_isin != position_isin]
    update_portfolio(portfolio)


# ── Таблица текущих позиций ──────────────────────────────────────────────────


def render_positions_table(portfolio: Portfolio, universe: Sequence[BondRecord]) -> None:
    """Таблица купленных позиций с рыночными данными, скором и удалением.

    Колонки:

    * **Открыть** — ссылка на детальную страницу бумаги (открывает экран
      деталей в табе «Скринер» через query-param ``?bond=SECID``).
    * **Скор** — текущий профильный скор бумаги (по выбранному
      риск-профилю портфеля). Если бумаги нет в актуальном универсе
      MOEX (например, делистинг) — прочерк.
    * **Удалить** — ссылка-иконка, открывающая ту же страницу с
      query-param ``?pos_remove=ISIN&portfolio_id=...``. ``app.py``
      перехватывает параметр и удаляет позицию из портфеля.
    """
    st.subheader(f"Текущие позиции · {len(portfolio.positions)}")

    if not portfolio.positions:
        st.info(
            "Позиций ещё нет. Используйте «Автосоставить» или добавьте бумагу вручную в форме выше."
        )
        return

    universe_by_isin = {b.isin: b for b in universe}

    # Считаем скоры по профилю на копии активных бумаг, чтобы не мутировать
    # общий объект.
    live_bonds_for_score: list[BondRecord] = []
    for position in portfolio.positions:
        live = universe_by_isin.get(position.isin)
        if live is not None:
            live_bonds_for_score.append(live)
    score_by_isin: dict[str, float | None] = {}
    ytm_net_by_isin: dict[str, float | None] = {}
    if live_bonds_for_score:
        scored = score_bonds_for_profile(list(live_bonds_for_score), portfolio.risk_profile)
        score_by_isin = {b.isin: b.score for b in scored}
        ytm_net_by_isin = {b.isin: b.ytm_net for b in scored}

    rows: list[dict] = []
    for position in portfolio.positions:
        live = universe_by_isin.get(position.isin)
        live_price_pct = live.last_price if live else None
        live_dirty = live.dirty_price_rub if live else None
        current_value = (live_dirty or position.purchase_dirty_price_rub) * position.bonds_count
        change_rub = current_value - position.purchase_amount_rub
        score_value = score_by_isin.get(position.isin)
        ytm_net_value = ytm_net_by_isin.get(position.isin)
        detail_url = f"?{DETAIL_QUERY_PARAM}={position.secid}"
        remove_url = f"?pos_remove={position.isin}&portfolio_id={portfolio.id}"
        rows.append(
            {
                "Детали": detail_url,
                "Тикер": position.secid,
                "Наименование": position.name,
                "Скор": round(score_value, 1) if score_value is not None else None,
                "YTM нетто, %": round(ytm_net_value, 2) if ytm_net_value is not None else None,
                "Источник": _POSITION_SOURCE_LABELS.get(position.source, position.source.value),
                "Лотов": position.lots,
                "Облиг.": position.bonds_count,
                "Куплена": position.purchase_date.isoformat(),
                "Цена покупки, %": round(position.purchase_clean_price_pct, 2),
                "Цена сейчас, %": round(live_price_pct, 2) if live_price_pct else None,
                "Вложено, ₽": round(position.purchase_amount_rub, 0),
                "Стоимость сейчас, ₽": round(current_value, 0),
                "Δ, ₽": round(change_rub, 0),
                "Погашение": position.maturity_date.isoformat() if position.maturity_date else "—",
                "Оферта": position.offer_date.isoformat() if position.offer_date else "—",
                "Решение по оферте": _put_offer_decision_label(position.put_offer_decision),
                "ISIN": position.isin,
                "Удалить": remove_url,
            }
        )

    df = pd.DataFrame(rows)
    rub_format_int = "%'\u00a0,.0f"
    st.dataframe(
        df,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Детали": st.column_config.LinkColumn(
                # Пустой label — как в скринере; визуально склеиваем
                # action-колонки в одну группу без подписи.
                "",
                display_text=":material/info:",
                help="Открыть страницу бумаги в табе «Скринер».",
                pinned=True,
                width="small",
            ),
            "Скор": st.column_config.NumberColumn(
                format="%.1f",
                help=(
                    f"Скор бумаги по риск-профилю «{RISK_PROFILE_LABELS[portfolio.risk_profile]}»."
                ),
            ),
            "YTM нетто, %": st.column_config.NumberColumn(
                format="%.2f%%",
                help=(
                    "YTM нетто = ГОДОВАЯ доходность бумаги к погашению после "
                    "НДФЛ. Реальный вклад бумаги в прибыль портфеля = "
                    "purchase_amount × ((1 + YTM)^(дней до погашения / 365) − 1). "
                    "Для коротких бумаг (2–4 месяца) вклад значительно "
                    "меньше, чем YTM × горизонт_лет."
                ),
            ),
            "Вложено, ₽": st.column_config.NumberColumn(format=rub_format_int),
            "Стоимость сейчас, ₽": st.column_config.NumberColumn(format=rub_format_int),
            "Δ, ₽": st.column_config.NumberColumn(format=rub_format_int),
            "Цена покупки, %": st.column_config.NumberColumn(format="%.2f%%"),
            "Цена сейчас, %": st.column_config.NumberColumn(format="%.2f%%"),
            "Удалить": st.column_config.LinkColumn(
                # Пустой label — действие и так понятно из иконки.
                "",
                display_text=":material/delete:",
                help=(
                    "Удалить позицию из портфеля. Клик мгновенно применит "
                    "изменение через query-param и перезагрузит страницу."
                ),
                width="small",
            ),
        },
    )


def _put_offer_decision_label(decision: PutOfferDecision) -> str:
    return {
        PutOfferDecision.PENDING: "—",
        PutOfferDecision.EXERCISE: "Предъявить",
        PutOfferDecision.HOLD: "Держать",
    }[decision]


# ── Слоты реинвестиций ───────────────────────────────────────────────────────


def render_reinvestment_slots(
    portfolio: Portfolio,
    plan: PortfolioPlan,
    universe: Sequence[BondRecord],
) -> None:
    """Список будущих слотов с возможностью переназначить бумагу."""
    st.subheader(f"Запланированные реинвестиции · {len(plan.resolved_slots)}")
    st.caption(
        f"После каждого погашения / оферты планировщик подбирает замену в "
        f"универсе MOEX (учитывая риск-профиль и горизонт). Дата покупки "
        f"замены — дата события + {REINVESTMENT_GAP_DAYS} дн. сеттлмент-гэп. "
        "В блоке ниже можно вручную переназначить бумагу — пересчёт "
        "произойдёт сразу."
    )

    if not plan.resolved_slots:
        st.info("Реинвестиций в горизонте нет — все позиции погашаются после или плана нет.")
        return

    universe_by_isin = {b.isin: b for b in universe}
    profile_universe = risk_profile_filter(list(universe), portfolio.risk_profile)
    profile_universe_by_isin = {b.isin: b for b in profile_universe}

    for idx, slot in enumerate(plan.resolved_slots):
        with st.container(border=True):
            _render_single_slot(
                slot,
                idx,
                portfolio,
                universe_by_isin,
                profile_universe_by_isin,
            )


def _render_single_slot(
    slot: ReinvestmentSlot,
    idx: int,
    portfolio: Portfolio,
    universe_by_isin: dict[str, BondRecord],
    profile_universe_by_isin: dict[str, BondRecord],
) -> None:
    """Рендер одного слота реинвестиции с селектом для переопределения.

    В селект попадают только бумаги, прошедшие
    :func:`core.portfolio_planner.validate_replacement_bond`: погашение
    строго после ``slot.purchase_date + MIN_REPLACEMENT_HORIZON_DAYS`` и
    не позже горизонта портфеля. Это критически важно: если бумага
    гасится до даты покупки, build_plan эмитит maturity-событие в
    прошлое относительно purchase, и cash «удваивается» в итоговых
    цифрах (см. историю багов в AGENTS.md).
    """
    reason_label = _TRIGGER_REASON_LABELS.get(slot.trigger_reason, slot.trigger_reason.value)

    source_position_name = "—"
    if slot.source_position_isin:
        for position in portfolio.positions:
            if position.isin == slot.source_position_isin:
                source_position_name = position.name
                break

    col_info, col_select = st.columns([2, 3])

    with col_info:
        st.markdown(
            f"**{reason_label}** · `{slot.trigger_date.isoformat()}` "
            f"→ покупка `{slot.purchase_date.isoformat()}`"
        )
        st.caption(
            f"Из позиции: {source_position_name} · "
            f"Ожидаемый кэш: {format_rub(slot.expected_cash_rub, decimals=0)}"
        )

    with col_select:
        # Кандидаты для ручного выбора строятся тем же fallback-принципом,
        # что и select_replacement в планировщике:
        #   1) основной профиль портфеля;
        #   2) NORMAL как fallback;
        #   3) любые бумаги без дефолта.
        # На каждом уровне применяется validate_replacement_bond, чтобы
        # исключить временно-невалидные бумаги (матью ≤ purchase_date и т.п.).
        def _valid_isins_from(source: dict[str, BondRecord]) -> list[str]:
            return [
                isin
                for isin, bond in source.items()
                if validate_replacement_bond(
                    bond,
                    slot_purchase_date=slot.purchase_date,
                    horizon=portfolio.horizon_date,
                )
                is None
            ]

        candidates_isins = _valid_isins_from(profile_universe_by_isin)

        fallback_label: str = ""
        if not candidates_isins and portfolio.risk_profile != RiskProfile.NORMAL:
            normal_by_isin = {
                b.isin: b
                for b in risk_profile_filter(list(universe_by_isin.values()), RiskProfile.NORMAL)
            }
            candidates_isins = _valid_isins_from(normal_by_isin)
            if candidates_isins:
                fallback_label = "NORMAL"

        if not candidates_isins:
            no_default_by_isin = {
                isin: b
                for isin, b in universe_by_isin.items()
                if not b.has_default and not b.has_technical_default
            }
            candidates_isins = _valid_isins_from(no_default_by_isin)
            if candidates_isins:
                fallback_label = "без профильных ограничений"

        if fallback_label:
            st.info(
                f"Под профиль «{portfolio.risk_profile.value}» нет кандидатов в этом окне. "
                f"Показаны бумаги ({fallback_label}) — планировщик тоже использует их "
                "как fallback, чтобы не держать деньги в кэше."
            )

        # Сортируем: сначала те, что помещаются в ожидаемый кэш
        candidates_isins.sort(
            key=lambda isin: (
                (universe_by_isin.get(isin) is None),
                (universe_by_isin[isin].price_per_lot_rub or 0)
                if isin in universe_by_isin
                else 1e12,
            )
        )

        if not candidates_isins:
            st.warning(
                f"Нет бумаг с погашением между {slot.purchase_date.isoformat()} и "
                f"{portfolio.horizon_date.isoformat()}. Деньги останутся в кэше. "
                "Рассмотрите расширение горизонта портфеля."
            )
            return

        if not slot.suggested_isin and not slot.confirmed_isin:
            st.info(
                "Планировщик не нашёл автозамену под профиль и горизонт. "
                "Можете выбрать бумагу вручную ниже — учитываются только "
                "пригодные к покупке кандидаты (погашение строго после "
                f"{slot.purchase_date.isoformat()}). Если не выбирать, "
                "деньги после погашения останутся в кэше."
            )

        # Выбор по умолчанию: confirmed_isin > suggested_isin > первый
        default_isin = slot.confirmed_isin or slot.suggested_isin
        if default_isin and default_isin in candidates_isins:
            default_index = candidates_isins.index(default_isin)
        else:
            default_index = 0

        selected_isin = st.selectbox(
            "Бумага замены",
            options=candidates_isins,
            index=default_index,
            format_func=lambda isin: _format_candidate_label(
                isin, universe_by_isin, slot.expected_cash_rub
            ),
            key=f"slot_select_{portfolio.id}_{idx}",
        )

        # «Применить выбор» disabled, если selected совпадает с тем, что
        # уже в плане (effective_isin). Это включает случай, когда
        # confirmed=None, suggested=X, selected=X: ничего применять не
        # нужно. И случай confirmed=X, selected=X — тоже.
        effective_now = slot.effective_isin
        col_apply, col_reset = st.columns([1, 1])
        with col_apply:
            if st.button(
                "Применить выбор",
                key=f"slot_apply_{portfolio.id}_{idx}",
                type="primary",
                use_container_width=True,
                disabled=(selected_isin == effective_now),
            ):
                _apply_slot_override(portfolio, slot, selected_isin)
                st.rerun()
        with col_reset:
            if st.button(
                "Сбросить override",
                key=f"slot_reset_{portfolio.id}_{idx}",
                use_container_width=True,
                disabled=slot.confirmed_isin is None,
            ):
                _apply_slot_override(portfolio, slot, None)
                st.rerun()


def _format_candidate_label(
    isin: str,
    universe_by_isin: dict[str, BondRecord],
    expected_cash: float,
) -> str:
    """Подпись для опции в селекте слота: тикер, имя, цена/доходность, флаг доступности."""
    bond = universe_by_isin.get(isin)
    if bond is None:
        return f"{isin} (нет в универсе)"
    parts = [f"{bond.secid} — {bond.name}"]
    if bond.price_per_lot_rub:
        parts.append(f"лот {format_rub(bond.price_per_lot_rub, decimals=0)}")
        if bond.price_per_lot_rub > expected_cash:
            parts.append("(превышает кэш)")
    if bond.ytm_net is not None:
        parts.append(f"YTM нетто {bond.ytm_net:.2f}%")
    if bond.credit_rating:
        parts.append(bond.credit_rating)
    return " · ".join(parts)


def _apply_slot_override(
    portfolio: Portfolio,
    slot: ReinvestmentSlot,
    new_isin: str | None,
) -> None:
    """Сохранить пользовательский override для слота.

    Слоты — производная сущность (пересчитываются при каждом ``build_plan``),
    но поле ``confirmed_isin`` хранится между перезапусками. Поэтому мы
    upsert-им слот в ``portfolio.slots`` по ключу ``source_position_isin``.
    """
    target_slot: ReinvestmentSlot | None = None
    for existing in portfolio.slots:
        if existing.source_position_isin == slot.source_position_isin:
            target_slot = existing
            break
    if target_slot is None:
        target_slot = ReinvestmentSlot(
            trigger_date=slot.trigger_date,
            trigger_reason=slot.trigger_reason,
            expected_cash_rub=slot.expected_cash_rub,
            suggested_isin=slot.suggested_isin,
            confirmed_isin=new_isin,
            gap_days=slot.gap_days,
            source_position_isin=slot.source_position_isin,
        )
        portfolio.slots.append(target_slot)
    else:
        target_slot.confirmed_isin = new_isin
        target_slot.trigger_date = slot.trigger_date
        target_slot.expected_cash_rub = slot.expected_cash_rub
    update_portfolio(portfolio)


# ── Таймлайн событий ─────────────────────────────────────────────────────────


def render_timeline(plan: PortfolioPlan) -> None:
    """Хронологическая таблица всех cashflow-событий портфеля."""
    st.subheader("Cashflow-таймлайн")

    if not plan.events:
        st.info("Событий нет — добавьте бумагу или соберите портфель автоматически.")
        return

    rows: list[dict] = []
    running_cash = plan.portfolio.cash_balance_rub
    for event in plan.events:
        running_cash += event.amount_rub
        rows.append(
            {
                "Дата": event.date.isoformat(),
                "Событие": _EVENT_KIND_LABELS.get(event.kind, event.kind),
                "Описание": event.description,
                "Сумма, ₽": round(event.amount_rub, 0),
                "Кэш-баланс, ₽": round(running_cash, 0),
                "Прогноз": "Да" if event.is_projected else "Факт",
            }
        )
    df = pd.DataFrame(rows)
    rub_format_int = "%'\u00a0,.0f"
    st.dataframe(
        df,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Сумма, ₽": st.column_config.NumberColumn(format=rub_format_int),
            "Кэш-баланс, ₽": st.column_config.NumberColumn(format=rub_format_int),
        },
    )


# ── Trading API stub ─────────────────────────────────────────────────────────


def render_trading_stub_section() -> None:
    """Заглушка для будущей интеграции с биржевой торговлей.

    Сама кнопка disabled — реальный submit бросает ``NotImplementedError``
    (см. :mod:`data.trading_client`). Цель блока — показать пользователю,
    что точка интеграции зарезервирована, и дать каркас, в который встроится
    рабочий код после стабилизации основной логики портфеля.
    """
    st.subheader("Торговля через API")
    st.caption(
        "В будущей версии модуль сможет отправлять заявки на биржу через "
        "T-Invest API (тот же токен, что используется для обогащения "
        "данных). Сейчас функция сознательно отключена — см. "
        "``data/trading_client.py`` и AGENTS.md → «Расширение: API торговли»."
    )
    st.button(
        "Отправить план на биржу (недоступно)",
        disabled=True,
        help="Включится после релиза v2 с поддержкой sandbox/production-режимов.",
    )


# ── Конвертеры строк (вспомогательное) ──────────────────────────────────────


def _format_event(event: CashflowEvent) -> str:
    """Человекочитаемое описание события для лога/тоста."""
    return f"{event.date.isoformat()} · {_EVENT_KIND_LABELS.get(event.kind, event.kind)}: {event.description}"
