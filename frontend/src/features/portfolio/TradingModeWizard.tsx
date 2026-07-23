import { Link } from "react-router-dom";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ChevronRight,
  Loader2,
  Plus,
  ServerOff,
  Trash2,
  Unlink,
  Wifi,
} from "lucide-react";
import { api } from "@/api/client";
import type { AccountPreview, BrokerAccount, Portfolio } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogRoot,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { useSubscriptionPaywall } from "@/features/billing/SubscriptionPaywallProvider";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";

const MODE_LABELS: Record<string, { label: string; className: string }> = {
  simulation: {
    label: "Симуляция",
    className: "bg-blue-500/15 text-blue-700 dark:text-blue-400",
  },
  trading: {
    label: "Торговля",
    className: "bg-green-500/15 text-green-700 dark:text-green-400",
  },
};

interface Props {
  portfolio: Portfolio;
  sandboxConfigured: boolean;
  productionConfigured: boolean;
  tradingConfigLoaded?: boolean;
  onPortfolioDeleted?: (portfolioId: string) => void;
}

type WizardStep = "kind" | "account" | "confirm";
type AccountKind = "sandbox" | "production";

function resolveDefaultKind(
  sandboxConfigured: boolean,
  productionConfigured: boolean,
): AccountKind {
  if (productionConfigured && !sandboxConfigured) return "production";
  return "sandbox";
}

function needsKindSelection(
  sandboxConfigured: boolean,
  productionConfigured: boolean,
): boolean {
  return sandboxConfigured && productionConfigured;
}

export function TradingModeBadge({ portfolio }: { portfolio: Portfolio }) {
  const cfg = MODE_LABELS[portfolio.mode] ?? MODE_LABELS.simulation;
  return (
    <Badge className={cn("font-medium", cfg.className)}>
      {cfg.label}
      {portfolio.account_kind && ` · ${portfolio.account_kind}`}
    </Badge>
  );
}

export function TradingModeWizard({
  portfolio,
  sandboxConfigured,
  productionConfigured,
  tradingConfigLoaded = true,
  onPortfolioDeleted,
}: Props) {
  const queryClient = useQueryClient();
  const showKindStep = needsKindSelection(sandboxConfigured, productionConfigured);
  const defaultKind = resolveDefaultKind(sandboxConfigured, productionConfigured);
  const [open, setOpen] = useState(false);
  const [detachOpen, setDetachOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<BrokerAccount | null>(null);
  const [step, setStep] = useState<WizardStep>(() => (showKindStep ? "kind" : "account"));
  const [kind, setKind] = useState<AccountKind>(defaultKind);
  const [selectedAccount, setSelectedAccount] = useState<BrokerAccount | null>(null);
  const [clearPayInRub, setClearPayInRub] = useState(
    () => String(Math.round(portfolio.initial_amount_rub)),
  );

  const {
    data: accounts,
    isLoading: accountsLoading,
    isError: accountsError,
  } = useQuery({
    queryKey: ["accounts", kind],
    queryFn: () => api.getAccounts(kind),
    enabled: open && step === "account",
    retry: 1,
  });

  const {
    data: accountPreview,
    isLoading: previewLoading,
  } = useQuery({
    queryKey: ["account-preview", portfolio.id, kind, selectedAccount?.id],
    queryFn: () =>
      api.getAccountPreview(portfolio.id, {
        account_id: selectedAccount!.id,
        kind,
      }),
    enabled: open && !!selectedAccount && (step === "account" || step === "confirm"),
    retry: 1,
  });

  const attachMutation = useMutation({
    mutationFn: () =>
      api.attachAccount(portfolio.id, {
        account_id: selectedAccount!.id,
        kind,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolios"] });
      queryClient.invalidateQueries({ queryKey: ["plan", portfolio.id] });
      queryClient.invalidateQueries({ queryKey: ["trading-state", portfolio.id] });
      queryClient.invalidateQueries({ queryKey: ["account-operations", portfolio.id] });
      setOpen(false);
      resetWizard();
    },
  });

  const clearAttachError = () => {
    attachMutation.reset();
  };

  const detachMutation = useMutation({
    mutationFn: () => api.detachAccount(portfolio.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolios"] });
      queryClient.invalidateQueries({ queryKey: ["plan", portfolio.id] });
      setDetachOpen(false);
    },
  });

  const createSandboxMutation = useMutation({
    mutationFn: () => {
      const payIn = Number(clearPayInRub.replace(/\s/g, "").replace(",", "."));
      if (!Number.isFinite(payIn) || payIn <= 0) {
        throw new Error("Укажите корректную сумму пополнения");
      }
      return api.createSandboxAccount({
        initial_amount_rub: payIn,
        name: `bond-monitor · ${portfolio.name}`,
      });
    },
    onSuccess: (account) => {
      queryClient.invalidateQueries({ queryKey: ["accounts", kind] });
      setSelectedAccount(account);
      clearAttachError();
    },
  });

  const deleteSandboxMutation = useMutation({
    mutationFn: (accountId: string) => api.deleteSandboxAccount(accountId),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["accounts", kind] });
      queryClient.invalidateQueries({ queryKey: ["portfolios"] });
      if (selectedAccount?.id === result.account_id) {
        setSelectedAccount(null);
        clearAttachError();
      }
      if (result.deleted_portfolio_id) {
        onPortfolioDeleted?.(result.deleted_portfolio_id);
      }
      setDeleteTarget(null);
    },
  });

  const clearAccountMutation = useMutation({
    mutationFn: () => {
      const payIn = Number(clearPayInRub.replace(/\s/g, "").replace(",", "."));
      if (!Number.isFinite(payIn) || payIn <= 0) {
        throw new Error("Укажите корректную сумму пополнения");
      }
      return api.clearAccountForAttach(portfolio.id, {
        account_id: selectedAccount!.id,
        kind,
        pay_in_rub: payIn,
      });
    },
    onSuccess: (preview) => {
      const newAccountId = preview.account_replaced?.new_id ?? selectedAccount?.id;
      if (preview.account_replaced?.new_id && selectedAccount) {
        setSelectedAccount({
          ...selectedAccount,
          id: preview.account_replaced.new_id,
        });
        queryClient.invalidateQueries({ queryKey: ["accounts", kind] });
      }
      queryClient.setQueryData(
        ["account-preview", portfolio.id, kind, newAccountId],
        preview,
      );
      clearAttachError();
    },
  });

  const resetWizard = () => {
    setStep(showKindStep ? "kind" : "account");
    setKind(defaultKind);
    setSelectedAccount(null);
    setClearPayInRub(String(Math.round(portfolio.initial_amount_rub)));
    clearAttachError();
  };

  const isTrading = portfolio.mode === "trading";
  const { openPaywall } = useSubscriptionPaywall();
  const { data: billing } = useQuery({
    queryKey: ["billing-status"],
    queryFn: () => api.getBillingStatus(),
    staleTime: 60_000,
  });
  const hasAttachEntitlement = Boolean(
    billing?.complimentary ||
      billing?.entitlements?.includes("portfolio.attach") ||
      billing?.has_active_access,
  );
  const canAttach = (sandboxConfigured || productionConfigured) && hasAttachEntitlement;

  if (isTrading) {
    return (
      <DialogRoot open={detachOpen} onOpenChange={setDetachOpen}>
        <DialogTrigger asChild>
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5"
            disabled={detachMutation.isPending}
          >
            <Unlink className="h-4 w-4" />
            Отвязать счёт
          </Button>
        </DialogTrigger>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Отвязать брокерский счёт</DialogTitle>
            <DialogDescription>
              Портфель вернётся в режим симуляции. Реальные операции на счёте{" "}
              <strong>{portfolio.account_id}</strong> затронуты не будут.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="destructive" onClick={() => detachMutation.mutate()}>
              {detachMutation.isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Unlink className="mr-2 h-4 w-4" />
              )}
              Отвязать
            </Button>
          </DialogFooter>
        </DialogContent>
      </DialogRoot>
    );
  }

  if (!tradingConfigLoaded || billing === undefined) {
    return (
      <Button size="sm" className="gap-1.5" disabled>
        <Loader2 className="h-4 w-4 animate-spin" />
        Перевести в торговлю
      </Button>
    );
  }

  if (!hasAttachEntitlement) {
    return (
      <Button
        size="sm"
        className="min-h-10 gap-1.5"
        onClick={() => openPaywall({ reason: "portfolio.attach" })}
      >
        <Wifi className="h-4 w-4" />
        Привязать счёт
      </Button>
    );
  }

  if (!canAttach) {
    return (
      <Button size="sm" className="min-h-10 gap-1.5" asChild>
        <Link to="/account">
          <Wifi className="h-4 w-4" />
          Настроить ключи
        </Link>
      </Button>
    );
  }

  return (
    <>
    <DialogRoot
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (!o) resetWizard();
      }}
    >
      <DialogTrigger asChild>
        <Button size="sm" className="gap-1.5">
          <Wifi className="h-4 w-4" />
          Перевести в торговлю
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Подключить брокерский счёт</DialogTitle>
          <DialogDescription>
            {step === "kind" && "Выберите контур T-Invest"}
            {step === "account" && "Выберите счёт"}
            {step === "confirm" &&
              `Подтвердите привязку счёта ${selectedAccount?.name}`}
          </DialogDescription>
        </DialogHeader>

        {/* Step 1: Kind — только если настроены оба токена */}
        {step === "kind" && showKindStep && (
          <div className="space-y-2">
            <KindButton
              title="Песочница (sandbox)"
              description="Виртуальные деньги, безопасно для тестирования стратегий"
              selected={kind === "sandbox"}
              onClick={() => {
                clearAttachError();
                setKind("sandbox");
              }}
            />
            <KindButton
              title="Боевой счёт (production)"
              description="Реальные деньги. Все операции будут отправляться на биржу."
              selected={kind === "production"}
              onClick={() => {
                clearAttachError();
                setKind("production");
              }}
              warning
            />
            <DialogFooter>
              <Button
                onClick={() => {
                  clearAttachError();
                  setStep("account");
                }}
                className="w-full"
              >
                Далее
                <ChevronRight className="ml-2 h-4 w-4" />
              </Button>
            </DialogFooter>
          </div>
        )}

        {/* Step 2: Account */}
        {step === "account" && (
          <div className="space-y-2">
            {kind === "sandbox" && (
              <div className="space-y-2 rounded-lg border border-dashed border-primary/30 bg-primary/5 p-3">
                <p className="text-sm font-medium">Создать новый счёт</p>
                <label className="block space-y-1.5">
                  <span className="text-xs text-muted-foreground">Начальный баланс, ₽</span>
                  <Input
                    type="number"
                    min={1000}
                    step={10000}
                    value={clearPayInRub}
                    onChange={(e) => setClearPayInRub(e.target.value)}
                    disabled={createSandboxMutation.isPending}
                  />
                </label>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="w-full gap-1.5"
                  disabled={
                    createSandboxMutation.isPending ||
                    !Number.isFinite(
                      Number(clearPayInRub.replace(/\s/g, "").replace(",", ".")),
                    ) ||
                    Number(clearPayInRub.replace(/\s/g, "").replace(",", ".")) <= 0
                  }
                  onClick={() => createSandboxMutation.mutate()}
                >
                  {createSandboxMutation.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Plus className="h-4 w-4" />
                  )}
                  Создать счёт в песочнице
                </Button>
                {createSandboxMutation.isError && (
                  <p className="text-xs text-destructive">
                    {formatAttachError(createSandboxMutation.error)}
                  </p>
                )}
              </div>
            )}
            {accountsLoading && (
              <div className="flex justify-center py-4">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            )}
            {accounts && accounts.length > 0 && (
              <p className="text-xs font-medium text-muted-foreground">Или выберите существующий</p>
            )}
            {accounts?.map((acc) => (
              <div
                key={acc.id}
                className={cn(
                  "flex items-stretch gap-1 rounded-lg border transition-colors",
                  selectedAccount?.id === acc.id
                    ? "border-primary bg-primary/5"
                    : "border-border hover:bg-muted/50",
                  acc.linked_portfolio && "border-amber-500/40",
                )}
              >
                <button
                  type="button"
                  onClick={() => {
                    clearAttachError();
                    setSelectedAccount(acc);
                  }}
                  className="min-w-0 flex-1 p-3 text-left"
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="font-medium">{acc.name}</p>
                    {acc.linked_portfolio && (
                      <Badge
                        variant="outline"
                        className="shrink-0 border-amber-500/40 bg-amber-500/10 text-amber-900 dark:text-amber-300"
                      >
                        Занят
                      </Badge>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground">{acc.id}</p>
                  {acc.linked_portfolio && (
                    <p className="mt-1 text-xs text-amber-800 dark:text-amber-300">
                      Привязан к портфелю «{acc.linked_portfolio.name}»
                    </p>
                  )}
                </button>
                {kind === "sandbox" && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="my-1 mr-1 h-8 w-8 shrink-0 self-center text-muted-foreground hover:text-destructive"
                    aria-label="Удалить счёт"
                    onClick={() => setDeleteTarget(acc)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                )}
              </div>
            ))}
            {(accountsError || accounts?.length === 0) && !accountsLoading && (
              <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-border bg-muted/30 px-4 py-6 text-center">
                <ServerOff className="h-8 w-8 text-muted-foreground" />
                <div className="space-y-1">
                  <p className="text-sm font-medium">Счета не найдены</p>
                  <p className="text-xs text-muted-foreground">
                    {accountsError
                      ? "Не удалось подключиться к T-Инвестициям. Проверьте, что токен задан корректно."
                      : "Токен настроен, но активных счетов не найдено. Убедитесь, что у токена есть доступ к вашим счетам в T-Инвестициях."}
                  </p>
                  <p className="text-xs text-muted-foreground/70">
                    Токен настраивается в переменной окружения{" "}
                    <code className="font-mono">
                      {kind === "sandbox"
                        ? "T_TRADING_TOKEN_SANDBOX"
                        : "T_TRADING_TOKEN_PRODUCTION"}
                    </code>
                  </p>
                </div>
              </div>
            )}
            {selectedAccount && (
              <>
                {(selectedAccount.linked_portfolio ?? accountPreview?.linked_portfolio) && (
                  <div className="flex items-start gap-2 rounded-lg bg-amber-500/10 p-3 text-sm text-amber-900 dark:text-amber-300">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                    <span>
                      Этот счёт уже привязан к портфелю «
                      {(accountPreview?.linked_portfolio ?? selectedAccount.linked_portfolio)!.name}
                      ». Отвяжите его там или выберите другой счёт.
                    </span>
                  </div>
                )}
                <AccountSecuritiesPanel
                preview={accountPreview}
                loading={previewLoading}
                kind={kind}
                clearPayInRub={clearPayInRub}
                onClearPayInRubChange={setClearPayInRub}
                portfolioBudgetRub={portfolio.initial_amount_rub}
                onClear={() => clearAccountMutation.mutate()}
                clearing={clearAccountMutation.isPending}
                clearError={clearAccountMutation.error}
              />
              </>
            )}
            <DialogFooter>
              {showKindStep && (
                <Button
                  variant="outline"
                  onClick={() => {
                    clearAttachError();
                    setStep("kind");
                  }}
                >
                  Назад
                </Button>
              )}
              <Button
                disabled={
                  !selectedAccount ||
                  Boolean(
                    selectedAccount.linked_portfolio ?? accountPreview?.linked_portfolio,
                  )
                }
                onClick={() => {
                  clearAttachError();
                  setStep("confirm");
                }}
              >
                Далее
                <ChevronRight className="ml-2 h-4 w-4" />
              </Button>
            </DialogFooter>
          </div>
        )}

        {/* Step 3: Confirm */}
        {step === "confirm" && selectedAccount && (
          <div className="space-y-4">
            <div className="rounded-lg bg-muted/50 p-4 text-sm">
              <div className="flex justify-between py-1">
                <span className="text-muted-foreground">Счёт</span>
                <span className="font-medium">{selectedAccount.name}</span>
              </div>
              <div className="flex justify-between py-1">
                <span className="text-muted-foreground">ID счёта</span>
                <span className="font-mono text-xs">{selectedAccount.id}</span>
              </div>
              <div className="flex justify-between py-1">
                <span className="text-muted-foreground">Контур</span>
                <span className="font-medium">{kind}</span>
              </div>
              <div className="flex justify-between py-1">
                <span className="text-muted-foreground">Портфель</span>
                <span className="font-medium">{portfolio.name}</span>
              </div>
              {accountPreview && (
                <div className="flex justify-between border-t border-border/60 pt-2 py-1">
                  <span className="text-muted-foreground">Свободные средства</span>
                  <span className="font-medium">
                    {accountPreview.money_rub.toLocaleString("ru-RU")} ₽
                  </span>
                </div>
              )}
            </div>
            <AccountSecuritiesPanel
              preview={accountPreview}
              loading={previewLoading}
              kind={kind}
              clearPayInRub={clearPayInRub}
              onClearPayInRubChange={setClearPayInRub}
              portfolioBudgetRub={portfolio.initial_amount_rub}
              onClear={() => clearAccountMutation.mutate()}
              clearing={clearAccountMutation.isPending}
              clearError={clearAccountMutation.error}
              showBlockers
            />
            {accountPreview && !accountPreview.can_attach && (
              <div className="flex items-start gap-2 rounded-lg bg-destructive/10 p-3 text-sm text-destructive">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <div className="space-y-1">
                  {accountPreview.blockers.map((blocker) => (
                    <p key={blocker}>{blocker}</p>
                  ))}
                </div>
              </div>
            )}
            {accountPreview?.warnings.map((warning) => (
              <div
                key={warning}
                className="flex items-start gap-2 rounded-lg bg-amber-500/10 p-3 text-sm text-amber-800 dark:text-amber-400"
              >
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{warning}</span>
              </div>
            ))}
            {kind === "production" && (
              <div className="flex items-start gap-2 rounded-lg bg-amber-500/10 p-3 text-sm text-amber-800 dark:text-amber-400">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>
                  Боевой счёт: операции будут отправляться на биржу. Убедитесь, что состав
                  портфеля соответствует вашим намерениям.
                </span>
              </div>
            )}
            {attachMutation.isError && (
              <div className="flex items-start gap-2 rounded-lg bg-destructive/10 p-3 text-sm text-destructive">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{formatAttachError(attachMutation.error)}</span>
              </div>
            )}
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => {
                  clearAttachError();
                  setStep("account");
                }}
              >
                Назад
              </Button>
              <Button
                onClick={() => attachMutation.mutate()}
                disabled={
                  attachMutation.isPending ||
                  previewLoading ||
                  clearAccountMutation.isPending ||
                  (accountPreview !== undefined && !accountPreview.can_attach)
                }
              >
                {attachMutation.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Wifi className="mr-2 h-4 w-4" />
                )}
                Привязать
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </DialogRoot>

    <DialogRoot open={deleteTarget !== null} onOpenChange={(o) => !o && setDeleteTarget(null)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Удалить счёт в песочнице</DialogTitle>
          <DialogDescription>
            {deleteTarget?.linked_portfolio ? (
              <>
                Счёт <strong>{deleteTarget.name}</strong> будет закрыт в T-Invest. Портфель «
                {deleteTarget.linked_portfolio.name}» также будет удалён без возможности
                восстановления.
              </>
            ) : (
              <>
                Счёт <strong>{deleteTarget?.name}</strong> будет закрыт в T-Invest. Это действие
                нельзя отменить.
              </>
            )}
          </DialogDescription>
        </DialogHeader>
        {deleteSandboxMutation.isError && (
          <p className="text-sm text-destructive">
            {formatAttachError(deleteSandboxMutation.error)}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => setDeleteTarget(null)}>
            Отмена
          </Button>
          <Button
            variant="destructive"
            onClick={() => deleteTarget && deleteSandboxMutation.mutate(deleteTarget.id)}
            disabled={deleteSandboxMutation.isPending}
          >
            {deleteSandboxMutation.isPending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Trash2 className="mr-2 h-4 w-4" />
            )}
            Удалить
          </Button>
        </DialogFooter>
      </DialogContent>
    </DialogRoot>
    </>
  );
}

function formatAttachError(error: unknown): string {
  if (!(error instanceof Error)) return "Не удалось привязать счёт";
  try {
    const parsed = JSON.parse(error.message) as { detail?: string };
    if (parsed.detail) return parsed.detail;
  } catch {
    // not JSON — use raw message
  }
  return error.message || "Не удалось привязать счёт";
}

function AccountSecuritiesPanel({
  preview,
  loading,
  kind,
  clearPayInRub,
  onClearPayInRubChange,
  portfolioBudgetRub,
  onClear,
  clearing,
  clearError,
  showBlockers = false,
}: {
  preview: AccountPreview | undefined;
  loading: boolean;
  kind: "sandbox" | "production";
  clearPayInRub: string;
  onClearPayInRubChange: (value: string) => void;
  portfolioBudgetRub: number;
  onClear: () => void;
  clearing: boolean;
  clearError: unknown;
  showBlockers?: boolean;
}) {
  if (loading) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-dashed border-border px-3 py-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Проверяем состав счёта…
      </div>
    );
  }

  if (!preview) return null;
  if (!preview.has_securities && !preview.reset_note) return null;

  const hasBonds = (preview.bond_positions?.length ?? 0) > 0;
  const canClearSandbox = kind === "sandbox" && preview.has_securities;
  const clearPayInInvalid =
    !Number.isFinite(Number(clearPayInRub.replace(/\s/g, "").replace(",", "."))) ||
    Number(clearPayInRub.replace(/\s/g, "").replace(",", ".")) <= 0;

  return (
    <div className="space-y-3 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-sm">
      {preview.has_securities && (
        <div className="flex items-start gap-2 text-amber-900 dark:text-amber-300">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <p>
            На счёте уже есть бумаги. Для привязки нужен «чистый» счёт — только рублёвый
            кэш.
          </p>
        </div>
      )}

      {hasBonds && (
        <div>
          <p className="mb-1 text-xs font-medium text-muted-foreground">Облигации</p>
          <ul className="space-y-1">
            {preview.bond_positions!.map((pos) => (
              <li
                key={pos.figi}
                className="flex justify-between gap-2 rounded-md bg-background/60 px-2 py-1"
              >
                <span className="font-medium">{pos.ticker || pos.figi.slice(0, 8)}</span>
                <span className="text-muted-foreground">
                  {pos.lots} лот · {pos.quantity} шт
                  {pos.current_price_pct != null && ` · ${pos.current_price_pct.toFixed(2)}%`}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {(preview.other_instruments?.length ?? 0) > 0 && (
        <div>
          <p className="mb-1 text-xs font-medium text-muted-foreground">Другие инструменты</p>
          <ul className="space-y-1">
            {preview.other_instruments!.map((ins) => (
              <li
                key={ins.figi || ins.ticker}
                className="flex justify-between gap-2 rounded-md bg-background/60 px-2 py-1"
              >
                <span className="font-medium">{ins.ticker || ins.figi.slice(0, 8)}</span>
                <span className="text-muted-foreground">
                  {ins.instrument_type} · {ins.quantity} шт
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {showBlockers && preview.blockers.length > 0 && kind === "production" && hasBonds && (
        <p className="text-xs text-muted-foreground">
          Продайте бумаги вручную через брокера или выберите другой счёт.
        </p>
      )}

      {preview.reset_note && (
        <div className="flex items-start gap-2 rounded-lg bg-blue-500/10 p-3 text-sm text-blue-900 dark:text-blue-300">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{preview.reset_note}</span>
        </div>
      )}

      {canClearSandbox && (
        <div className="space-y-2">
          <label className="block space-y-1.5">
            <span className="text-xs font-medium text-muted-foreground">
              Пополнение при пересоздании счёта, ₽
            </span>
            <Input
              type="number"
              min={1000}
              step={10000}
              value={clearPayInRub}
              onChange={(e) => onClearPayInRubChange(e.target.value)}
              disabled={clearing}
            />
            <span className="text-xs text-muted-foreground">
              По умолчанию — бюджет портфеля ({portfolioBudgetRub.toLocaleString("ru-RU")} ₽).
              Используется, если продажа бумаг через API недоступна.
            </span>
          </label>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="w-full gap-1.5 border-amber-500/40"
            onClick={onClear}
            disabled={clearing || clearPayInInvalid}
          >
            {clearing ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Trash2 className="h-4 w-4" />
            )}
            Освободить счёт
          </Button>
          <p className="text-xs text-muted-foreground">
            Продаст облигации или пересоздаст счёт в песочнице, если продажа через API
            недоступна.
          </p>
        </div>
      )}

      {clearError != null && (
        <p className="text-xs text-destructive">{formatAttachError(clearError)}</p>
      )}
    </div>
  );
}

function KindButton({
  title,
  description,
  selected,
  onClick,
  warning,
}: {
  title: string;
  description: string;
  selected: boolean;
  onClick: () => void;
  warning?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "w-full rounded-lg border p-3 text-left transition-colors",
        selected ? "border-primary bg-primary/5" : "border-border hover:bg-muted/50",
        warning && selected && "border-amber-500 bg-amber-500/5",
      )}
    >
      <p className="font-medium">{title}</p>
      <p className="text-xs text-muted-foreground">{description}</p>
    </button>
  );
}
