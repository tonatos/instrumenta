/** Canonical cashflow kind keys for filtering (aligned with backend journal kinds). */
export type CashflowKindKey =
  | "purchase"
  | "sale"
  | "coupon"
  | "maturity"
  | "put_offer"
  | "deposit"
  | "withdrawal"
  | "fee"
  | "tax"
  | "reconciliation";

export const CASHFLOW_KINDS_HIDDEN_BY_DEFAULT: CashflowKindKey[] = ["fee"];

export function defaultActiveCashflowKinds(available: CashflowKindKey[]): Set<CashflowKindKey> {
  const hidden = new Set(CASHFLOW_KINDS_HIDDEN_BY_DEFAULT);
  return new Set(available.filter((k) => !hidden.has(k)));
}

export const CASHFLOW_KIND_OPTIONS: Array<{ key: CashflowKindKey; label: string }> = [
  { key: "purchase", label: "Покупка" },
  { key: "sale", label: "Продажа" },
  { key: "coupon", label: "Купон" },
  { key: "maturity", label: "Погашение" },
  { key: "put_offer", label: "Пут-оферта" },
  { key: "deposit", label: "Пополнение" },
  { key: "withdrawal", label: "Вывод" },
  { key: "fee", label: "Комиссия" },
  { key: "tax", label: "Налог" },
  { key: "reconciliation", label: "Сверка" },
];

export function normalizeCashflowKind(kind: string): CashflowKindKey | string {
  const k = kind.toLowerCase();
  if (k === "buy" || k === "reinvest") return "purchase";
  return k;
}

export function cashflowKindLabel(kind: string): string {
  const key = normalizeCashflowKind(kind);
  const found = CASHFLOW_KIND_OPTIONS.find((o) => o.key === key);
  return found?.label ?? kind;
}

export function uniqueCashflowKindKeys(kinds: string[]): CashflowKindKey[] {
  const seen = new Set<string>();
  const out: CashflowKindKey[] = [];
  for (const kind of kinds) {
    const key = normalizeCashflowKind(kind);
    if (seen.has(key)) continue;
    seen.add(key);
    if (CASHFLOW_KIND_OPTIONS.some((o) => o.key === key)) {
      out.push(key as CashflowKindKey);
    }
  }
  return out.sort((a, b) => {
    const ai = CASHFLOW_KIND_OPTIONS.findIndex((o) => o.key === a);
    const bi = CASHFLOW_KIND_OPTIONS.findIndex((o) => o.key === b);
    return ai - bi;
  });
}
