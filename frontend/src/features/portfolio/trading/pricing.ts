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
