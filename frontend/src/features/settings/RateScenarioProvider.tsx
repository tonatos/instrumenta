import { createContext, useContext, useEffect, useState } from "react";
import {
  getRateScenario,
  setRateScenario as persistRateScenario,
  subscribeRateScenario,
  type RateScenario,
} from "@/features/settings/durationPreferences";

const RateScenarioContext = createContext<{
  rateScenario: RateScenario;
  setRateScenario: (value: RateScenario) => void;
} | null>(null);

export function RateScenarioProvider({ children }: { children: React.ReactNode }) {
  const [rateScenario, setRateScenarioState] = useState<RateScenario>(() => getRateScenario());

  useEffect(() => subscribeRateScenario(() => setRateScenarioState(getRateScenario())), []);

  const setRateScenario = (value: RateScenario) => {
    persistRateScenario(value);
    setRateScenarioState(value);
  };

  return (
    <RateScenarioContext.Provider value={{ rateScenario, setRateScenario }}>
      {children}
    </RateScenarioContext.Provider>
  );
}

export function useRateScenario() {
  const ctx = useContext(RateScenarioContext);
  if (!ctx) throw new Error("useRateScenario must be used within RateScenarioProvider");
  return ctx;
}
