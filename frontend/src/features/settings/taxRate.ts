/** Allowed personal НДФЛ rates (percent). 0 = ignore tax. */
export const TAX_RATE_OPTIONS = [
  { value: 0, label: "Не учитывать налог" },
  { value: 13, label: "13%" },
  { value: 15, label: "15%" },
  { value: 18, label: "18%" },
  { value: 20, label: "20%" },
  { value: 22, label: "22%" },
] as const;

export type TaxRatePct = (typeof TAX_RATE_OPTIONS)[number]["value"];

export function taxRateLabel(pct: number): string {
  const opt = TAX_RATE_OPTIONS.find((o) => o.value === pct);
  return opt?.label ?? `${pct}%`;
}
