export type RateScenario = "hold" | "cut" | "hike";

const STORAGE_KEY = "bond_monitor_rate_scenario";
const DEFAULT_SCENARIO: RateScenario = "hold";

type Listener = () => void;
const listeners = new Set<Listener>();

function notify() {
  for (const listener of listeners) {
    listener();
  }
}

export function getRateScenario(): RateScenario {
  if (typeof window === "undefined") return DEFAULT_SCENARIO;
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === "hold" || stored === "cut" || stored === "hike") {
    return stored;
  }
  return DEFAULT_SCENARIO;
}

export function setRateScenario(value: RateScenario): void {
  localStorage.setItem(STORAGE_KEY, value);
  notify();
}

export function subscribeRateScenario(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
