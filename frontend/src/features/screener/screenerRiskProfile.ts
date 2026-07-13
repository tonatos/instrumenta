export type ScreenerRiskProfile = "conservative" | "normal" | "aggressive";

const STORAGE_KEY = "bond_monitor_screener_risk_profile";
const DEFAULT_PROFILE: ScreenerRiskProfile = "normal";

type Listener = () => void;
const listeners = new Set<Listener>();

function notify() {
  for (const listener of listeners) {
    listener();
  }
}

export function getScreenerRiskProfile(): ScreenerRiskProfile {
  if (typeof window === "undefined") return DEFAULT_PROFILE;
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === "conservative" || stored === "normal" || stored === "aggressive") {
    return stored;
  }
  return DEFAULT_PROFILE;
}

export function setScreenerRiskProfile(value: ScreenerRiskProfile): void {
  localStorage.setItem(STORAGE_KEY, value);
  notify();
}

export function subscribeScreenerRiskProfile(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
