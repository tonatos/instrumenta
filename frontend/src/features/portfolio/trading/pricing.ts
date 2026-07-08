import { formatRub } from "@/lib/utils";

/** Чистая стоимость одного лота (% от номинала → ₽). */
export function lotCleanPriceRub({
  pricePct,
  faceValueRub,
  lotSize,
}: {
  pricePct: number;
  faceValueRub: number;
  lotSize: number;
}): number {
  return (pricePct / 100) * faceValueRub * lotSize;
}

/** Грязная стоимость одного лота (чистая + НКД на бумаги в лоте). */
export function lotDirtyPriceRub({
  pricePct,
  faceValueRub,
  lotSize,
  aciRubPerBond = 0,
}: {
  pricePct: number;
  faceValueRub: number;
  lotSize: number;
  aciRubPerBond?: number;
}): number {
  const cleanPerBond = (pricePct / 100) * faceValueRub;
  return (cleanPerBond + aciRubPerBond) * lotSize;
}

export function formatLotPriceHint({
  pricePct,
  faceValueRub,
  lotSize,
  aciRubPerBond = 0,
}: {
  pricePct: number;
  faceValueRub: number;
  lotSize: number;
  aciRubPerBond?: number;
}): string {
  const clean = lotCleanPriceRub({ pricePct, faceValueRub, lotSize });
  const dirty = lotDirtyPriceRub({ pricePct, faceValueRub, lotSize, aciRubPerBond });
  if (aciRubPerBond > 0) {
    return `${formatRub(clean)} чистая · ${formatRub(dirty)} с НКД`;
  }
  return `${formatRub(clean)} чистая`;
}

/** Подпись отклонения лимита от рыночной цены (для покупки). */
export function formatLimitVsMarket(
  marketPricePct: number,
  limitPricePct: number,
): string {
  const delta = marketPricePct - limitPricePct;
  if (Math.abs(delta) < 0.0001) return "лимит по рынку";
  if (delta > 0) return `лимит на ${delta.toFixed(2)}% ниже рынка`;
  return `лимит на ${Math.abs(delta).toFixed(2)}% выше рынка`;
}
