import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogRoot,
  DialogTitle,
} from "@/components/ui/dialog";
import { PlanCheckoutOptions } from "./PlanCheckoutOptions";
import { paywallCopyFor } from "./paywallCopy";
import {
  setSubscriptionPaywallHandler,
  type SubscriptionPaywallPayload,
  type SubscriptionPaywallReason,
} from "./subscriptionPaywallBus";

type SubscriptionPaywallContextValue = {
  openPaywall: (payload?: SubscriptionPaywallPayload) => void;
  closePaywall: () => void;
};

const SubscriptionPaywallContext = createContext<SubscriptionPaywallContextValue | null>(
  null,
);

export function SubscriptionPaywallProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<SubscriptionPaywallReason>("default");

  const openPaywall = useCallback((payload?: SubscriptionPaywallPayload) => {
    setReason(payload?.reason ?? "default");
    setOpen(true);
  }, []);

  const closePaywall = useCallback(() => setOpen(false), []);

  useEffect(() => {
    setSubscriptionPaywallHandler((payload) => openPaywall(payload));
    return () => setSubscriptionPaywallHandler(null);
  }, [openPaywall]);

  const value = useMemo(
    () => ({ openPaywall, closePaywall }),
    [openPaywall, closePaywall],
  );

  const copy = paywallCopyFor(reason);

  return (
    <SubscriptionPaywallContext.Provider value={value}>
      {children}
      <DialogRoot open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{copy.title}</DialogTitle>
            <DialogDescription>{copy.lead}</DialogDescription>
          </DialogHeader>
          <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
            {copy.bullets.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <div className="pt-2">
            <PlanCheckoutOptions compact />
          </div>
        </DialogContent>
      </DialogRoot>
    </SubscriptionPaywallContext.Provider>
  );
}

export function useSubscriptionPaywall(): SubscriptionPaywallContextValue {
  const ctx = useContext(SubscriptionPaywallContext);
  if (!ctx) {
    throw new Error("useSubscriptionPaywall must be used within SubscriptionPaywallProvider");
  }
  return ctx;
}
