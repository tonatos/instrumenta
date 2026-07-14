import type { Bond, HoldingView, PortfolioPosition } from "@/api/types";

/** Live-позиции в TRADING: факт со счёта + плановые INITIAL, ещё не купленные. */
export function buildTradingDisplayPositions(
  holdings: HoldingView[],
  planPositions: PortfolioPosition[],
  bondsByIsin: Map<string, Bond>,
): PortfolioPosition[] {
  const holdingIsins = new Set(holdings.map((h) => h.isin));

  const planByIsin = new Map(planPositions.map((p) => [p.isin, p]));

  const fromHoldings: PortfolioPosition[] = holdings.map((h) => {
    const bond = bondsByIsin.get(h.isin);
    const planPosition = planByIsin.get(h.isin);
    const bondsCount = h.lots * h.lot_size;
    const dirtyPerBond =
      h.market_value_rub != null && bondsCount > 0
        ? h.market_value_rub / bondsCount
        : ((bond?.last_price ?? 100) / 100) * (bond?.face_value ?? 1000);
    return {
      isin: h.isin,
      secid: bond?.secid ?? planPosition?.secid ?? h.isin,
      name: h.name,
      lots: h.lots,
      lot_size: h.lot_size,
      purchase_clean_price_pct: h.current_price_pct ?? bond?.last_price ?? 100,
      purchase_dirty_price_rub: dirtyPerBond,
      purchase_aci_rub: h.current_nkd_rub ?? 0,
      purchase_date: planPosition?.purchase_date ?? new Date().toISOString().slice(0, 10),
      purchase_amount_rub: h.market_value_rub ?? dirtyPerBond * bondsCount,
      coupon_rate: bond?.coupon_rate ?? planPosition?.coupon_rate ?? null,
      face_value: bond?.face_value ?? planPosition?.face_value ?? 1000,
      maturity_date: h.maturity_date ?? bond?.maturity_date ?? planPosition?.maturity_date ?? null,
      offer_date: planPosition?.offer_date ?? h.offer_date ?? bond?.offer_date ?? null,
      offer_submission_start: planPosition?.offer_submission_start ?? bond?.offer_submission_start ?? null,
      offer_submission_end: planPosition?.offer_submission_end ?? bond?.offer_submission_end ?? null,
      offer_price_pct: planPosition?.offer_price_pct ?? bond?.offer_price_pct ?? null,
      put_offer_decision: planPosition?.put_offer_decision ?? "pending",
      offer_kind: planPosition?.offer_kind ?? bond?.offer_kind ?? null,
      offer_window_status:
        planPosition?.offer_window_status ?? bond?.offer_window_status ?? null,
      source: planPosition?.source ?? "adopted",
      figi: h.figi,
      status: "active",
    };
  });

  const pendingPlan = planPositions
    .filter((p) => p.source === "initial" && !holdingIsins.has(p.isin))
    .map((p) => ({ ...p, status: "pending" as const }));

  return [...fromHoldings, ...pendingPlan];
}

export function resolveVisiblePositions(
  positions: PortfolioPosition[],
  isTrading: boolean,
  bondsByIsin: Map<string, Bond>,
  tradingAdvice?: { holdings: HoldingView[] },
): PortfolioPosition[] {
  if (!isTrading || !tradingAdvice) {
    return positions;
  }
  return buildTradingDisplayPositions(tradingAdvice.holdings, positions, bondsByIsin);
}
