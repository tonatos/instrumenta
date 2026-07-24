/** Appends ?start=support to a Telegram bot deep link. */
export function supportBotDeepLink(deepLink: string | undefined | null): string {
  const base = (deepLink ?? "").trim();
  if (!base) return "";
  if (base.includes("start=support")) return base;
  const q = base.indexOf("?");
  if (q >= 0) {
    const path = base.slice(0, q);
    const rest = base.slice(q + 1);
    return rest ? `${path}?start=support&${rest}` : `${path}?start=support`;
  }
  return `${base}?start=support`;
}
