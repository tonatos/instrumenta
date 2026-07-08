import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable,
  type FilterFn,
  type VisibilityState,
  type SortingState,
} from "@tanstack/react-table";
import {
  Download,
  RefreshCw,
  RotateCcw,
  Search,
  Settings2,
  Star,
} from "lucide-react";
import { api } from "@/api/client";
import type { Bond } from "@/api/types";
import { BondDetailSheet } from "@/features/screener/BondDetailSheet";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { PopoverContent, PopoverRoot, PopoverTrigger } from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip } from "@/components/ui/tooltip";
import { cn, formatDate, formatPct, formatRub } from "@/lib/utils";

const columnHelper = createColumnHelper<Bond>();

const RISK_LABELS: Record<number, string> = {
  0: "Неизвестен",
  1: "Низкий",
  2: "Умеренный",
  3: "Высокий",
};

const COUPON_TYPES = [
  { value: "fixed", label: "Фиксированный" },
  { value: "floating", label: "Плавающий" },
  { value: "variable", label: "Переменный" },
  { value: "unknown", label: "Неизвестен" },
];

const RISK_LEVELS = [
  { value: 1, label: "Низкий" },
  { value: 2, label: "Умеренный" },
  { value: 3, label: "Высокий" },
  { value: 0, label: "Неизвестен" },
];

const STORAGE_KEY = "screener_column_visibility";

const bondSearchFilter: FilterFn<Bond> = (row, _columnId, filterValue) => {
  const q = String(filterValue).trim().toLowerCase();
  if (!q) return true;
  const bond = row.original;
  return (
    bond.name.toLowerCase().includes(q) ||
    bond.secid.toLowerCase().includes(q) ||
    bond.isin.toLowerCase().includes(q)
  );
};

function loadColumnVisibility(): VisibilityState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw) as VisibilityState;
  } catch {}
  return {
    ytm: false,
    coupon_rate: false,
    maturity_date: false,
  };
}

export function ScreenerPage() {
  const [sorting, setSorting] = useState<SortingState>([{ id: "score", desc: true }]);
  const [globalFilter, setGlobalFilter] = useState("");
  const [selectedSecid, setSelectedSecid] = useState<string | null>(null);
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>(
    loadColumnVisibility,
  );
  const queryClient = useQueryClient();

  const { data: config } = useQuery({
    queryKey: ["config"],
    queryFn: api.getConfig,
  });

  // Filter state
  const [filterBy, setFilterBy] = useState<"effective" | "maturity">("effective");
  const [maxDays, setMaxDays] = useState<number | "">(config?.max_days ?? "");
  const [minVolume, setMinVolume] = useState<number | "">(config?.min_volume_rub ?? "");
  const [minYtm, setMinYtm] = useState<number | "">("");
  const [maxLotPrice, setMaxLotPrice] = useState<number | "">(0);
  const [couponTypes, setCouponTypes] = useState<string[]>([]);
  const [riskLevels, setRiskLevels] = useState<number[]>([]);
  const [hideSubordinated, setHideSubordinated] = useState(false);
  const [hideDefault, setHideDefault] = useState(true);

  // Apply config defaults once loaded
  useEffect(() => {
    if (config) {
      setMaxDays((v) => (v === "" ? config.max_days : v));
      setMinVolume((v) => (v === "" ? config.min_volume_rub : v));
    }
  }, [config]);

  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ["bonds", filterBy],
    queryFn: () => api.getBonds(filterBy),
  });

  const toggleFavorite = useMutation({
    mutationFn: async (bond: Bond) => {
      if (bond.is_favorite) await api.removeFavorite(bond.isin);
      else await api.addFavorite(bond.isin);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["bonds"] });
      queryClient.invalidateQueries({ queryKey: ["favorites"] });
    },
  });

  const filteredBonds = useMemo(() => {
    if (!data?.bonds) return [];
    return data.bonds.filter((b) => {
      if (maxDays !== "" && (b.days_to_maturity == null || b.days_to_maturity > maxDays)) {
        return false;
      }
      if (minVolume !== "") {
        const filterVol = b.prev_volume_rub ?? b.volume_rub;
        if (filterVol == null || filterVol < minVolume) {
          return false;
        }
      }
      if (minYtm !== "" && (b.ytm_net == null || b.ytm_net < minYtm)) {
        return false;
      }
      if (maxLotPrice && maxLotPrice > 0) {
        const lotPrice =
          b.last_price != null ? (b.last_price / 100) * b.face_value * b.lot_size : null;
        if (lotPrice != null && lotPrice > maxLotPrice) return false;
      }
      if (couponTypes.length > 0 && !couponTypes.includes(b.coupon_type)) {
        return false;
      }
      if (riskLevels.length > 0 && !riskLevels.includes(b.risk_level)) {
        return false;
      }
      if (hideSubordinated && b.warnings.some((w) => w.toLowerCase().includes("субординир"))) {
        return false;
      }
      if (
        hideDefault &&
        b.warnings.some(
          (w) =>
            w.toLowerCase().includes("дефолт") || w.toLowerCase().includes("технический дефолт"),
        )
      ) {
        return false;
      }
      return true;
    });
  }, [data?.bonds, maxDays, minVolume, minYtm, maxLotPrice, couponTypes, riskLevels, hideSubordinated, hideDefault]);

  const resetFilters = useCallback(() => {
    setFilterBy("effective");
    setMaxDays(config?.max_days ?? "");
    setMinVolume(config?.min_volume_rub ?? "");
    setMinYtm("");
    setMaxLotPrice(0);
    setCouponTypes([]);
    setRiskLevels([]);
    setHideSubordinated(false);
    setHideDefault(true);
    setGlobalFilter("");
  }, [config]);

  const handleColumnVisibility = useCallback((state: VisibilityState) => {
    setColumnVisibility(state);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }, []);

  const columns = useMemo(
    () => [
      columnHelper.display({
        id: "favorite",
        header: "",
        enableHiding: false,
        cell: ({ row }) => (
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            aria-label={row.original.is_favorite ? "Убрать из избранного" : "В избранное"}
            onClick={(e) => {
              e.stopPropagation();
              toggleFavorite.mutate(row.original);
            }}
          >
            <Star
              className={cn("h-4 w-4", row.original.is_favorite && "fill-amber-400 text-amber-400")}
            />
          </Button>
        ),
      }),
      columnHelper.accessor("name", {
        header: "Название",
        enableHiding: false,
        cell: (info) => (
          <button
            type="button"
            className="max-w-[200px] truncate text-left font-medium hover:underline"
            onClick={(e) => {
              e.stopPropagation();
              setSelectedSecid(info.row.original.secid);
            }}
          >
            {info.getValue()}
          </button>
        ),
      }),
      columnHelper.accessor("days_to_maturity", {
        header: "Дней",
        cell: (i) => i.getValue() ?? "—",
      }),
      columnHelper.accessor("ytm_net", {
        header: "YTM нетто",
        cell: (i) => formatPct(i.getValue()),
      }),
      columnHelper.accessor("ytm", {
        id: "ytm",
        header: "YTM брутто",
        cell: (i) => formatPct(i.getValue()),
      }),
      columnHelper.accessor("coupon_rate", {
        header: "Купон, %",
        cell: (i) => formatPct(i.getValue()),
      }),
      columnHelper.accessor("coupon_type", {
        header: "Тип купона",
        cell: (i) => {
          const labels: Record<string, string> = {
            fixed: "Фикс.",
            floating: "Плав.",
            variable: "Перем.",
            unknown: "—",
          };
          return labels[i.getValue()] ?? i.getValue();
        },
      }),
      columnHelper.accessor("risk_level", {
        header: "Риск",
        cell: (i) => {
          const v = i.getValue();
          const colorMap: Record<number, string> = {
            0: "bg-muted text-muted-foreground",
            1: "bg-green-500/15 text-green-700 dark:text-green-400",
            2: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
            3: "bg-red-500/15 text-red-700 dark:text-red-400",
          };
          return (
            <Badge className={cn("font-normal text-xs", colorMap[v])}>
              {RISK_LABELS[v] ?? "—"}
            </Badge>
          );
        },
      }),
      columnHelper.display({
        id: "lot_price",
        header: "Лот, ₽",
        cell: ({ row }) => {
          const b = row.original;
          if (b.last_price == null) return "—";
          return formatRub((b.last_price / 100) * b.face_value * b.lot_size);
        },
      }),
      columnHelper.accessor("credit_rating", {
        header: "Рейтинг",
        cell: (i) => i.getValue() ?? "—",
      }),
      columnHelper.accessor("score", {
        header: "Скор",
        cell: (i) => (
          <Badge variant={i.getValue() != null && i.getValue()! >= 60 ? "default" : "secondary"}>
            {i.getValue()?.toFixed(0) ?? "—"}
          </Badge>
        ),
      }),
      columnHelper.accessor("volume_rub", {
        header: "Объём",
        cell: (i) => formatRub(i.getValue()),
      }),
      columnHelper.accessor("maturity_date", {
        header: "Погашение",
        cell: (i) => formatDate(i.getValue()),
      }),
    ],
    [toggleFavorite],
  );

  const table = useReactTable({
    data: filteredBonds,
    columns,
    state: { sorting, globalFilter, columnVisibility },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    onColumnVisibilityChange: (updater) => {
      const next =
        typeof updater === "function"
          ? (updater as (old: VisibilityState) => VisibilityState)(columnVisibility)
          : updater;
      handleColumnVisibility(next);
    },
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    globalFilterFn: bondSearchFilter,
  });

  const exportCsv = () => {
    if (!filteredBonds.length) return;
    const header = ["secid", "isin", "name", "ytm_net", "score", "rating", "days", "coupon_type", "risk_level"];
    const rows = filteredBonds.map((b) =>
      [b.secid, b.isin, b.name, b.ytm_net, b.score, b.credit_rating, b.days_to_maturity, b.coupon_type, b.risk_level].join(","),
    );
    const blob = new Blob([[header.join(","), ...rows].join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "bonds.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  const toggleCouponType = (v: string) =>
    setCouponTypes((prev) => (prev.includes(v) ? prev.filter((x) => x !== v) : [...prev, v]));

  const toggleRiskLevel = (v: number) =>
    setRiskLevels((prev) => (prev.includes(v) ? prev.filter((x) => x !== v) : [...prev, v]));

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Скринер облигаций</h1>
          <p className="text-sm text-muted-foreground">
            {data
              ? `${table.getFilteredRowModel().rows.length} из ${data.count} · ${data.source}`
              : "Загрузка…"}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => refetch()} disabled={isFetching}>
            <RefreshCw className={cn("mr-2 h-4 w-4", isFetching && "animate-spin")} />
            Обновить
          </Button>
          <Button variant="outline" onClick={exportCsv}>
            <Download className="mr-2 h-4 w-4" />
            CSV
          </Button>
        </div>
      </div>

      {/* Filters */}
      <Card>
        <CardHeader className="pb-2 pt-4">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm font-semibold">Фильтры</CardTitle>
            <Button variant="ghost" size="sm" onClick={resetFilters} className="h-7 gap-1 text-xs">
              <RotateCcw className="h-3.5 w-3.5" />
              Сбросить
            </Button>
          </div>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {/* Search */}
          <div className="space-y-1 sm:col-span-2 lg:col-span-3">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                className="pl-9"
                placeholder="Поиск по названию, SECID или ISIN…"
                value={globalFilter}
                onChange={(e) => setGlobalFilter(e.target.value)}
              />
            </div>
          </div>

          {/* filterBy */}
          <div className="space-y-1.5">
            <div className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
              Как считать срок
              <Tooltip content="Определяет, по какой дате рассчитывается YTM и фильтрация по дням: до ближайшей оферты/погашения (effective) или только до даты погашения (maturity).">
                <button type="button" className="opacity-60 hover:opacity-100">
                  <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <circle cx="12" cy="12" r="10" /><path d="M12 16v-4M12 8h.01" strokeWidth="2" strokeLinecap="round"/>
                  </svg>
                </button>
              </Tooltip>
            </div>
            <div className="flex gap-2">
              {(["effective", "maturity"] as const).map((v) => (
                <button
                  key={v}
                  type="button"
                  onClick={() => setFilterBy(v)}
                  className={cn(
                    "flex-1 rounded-md border px-2 py-1.5 text-xs transition-colors",
                    filterBy === v
                      ? "border-primary bg-primary/10 font-medium text-primary"
                      : "border-border hover:bg-muted/50",
                  )}
                >
                  {v === "effective" ? "До оферты/погашения" : "До погашения"}
                </button>
              ))}
            </div>
          </div>

          {/* Max days */}
          <div className="space-y-1.5">
            <div className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
              Макс. дней до погашения
              <Tooltip content="Максимальное количество дней от сегодня до даты погашения (или оферты). Позволяет ограничить горизонт инвестиции.">
                <button type="button" className="opacity-60 hover:opacity-100">
                  <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <circle cx="12" cy="12" r="10" /><path d="M12 16v-4M12 8h.01" strokeWidth="2" strokeLinecap="round"/>
                  </svg>
                </button>
              </Tooltip>
            </div>
            <Input
              type="number"
              min={1}
              value={maxDays}
              onChange={(e) => setMaxDays(e.target.value === "" ? "" : Number(e.target.value))}
              placeholder="Без ограничения"
              className="h-8 text-sm"
            />
          </div>

          {/* Min volume */}
          <div className="space-y-1.5">
            <div className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
              Мин. объём торгов, ₽/день
              <Tooltip content="Минимальный объём торгов за предыдущую сессию. Отсеивает неликвидные бумаги. В таблице показывается объём за сегодня.">
                <button type="button" className="opacity-60 hover:opacity-100">
                  <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <circle cx="12" cy="12" r="10" /><path d="M12 16v-4M12 8h.01" strokeWidth="2" strokeLinecap="round"/>
                  </svg>
                </button>
              </Tooltip>
            </div>
            <Input
              type="number"
              min={0}
              value={minVolume}
              onChange={(e) => setMinVolume(e.target.value === "" ? "" : Number(e.target.value))}
              placeholder="0"
              className="h-8 text-sm"
            />
          </div>

          {/* Min YTM */}
          <div className="space-y-1.5">
            <div className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
              Мин. YTM нетто, %
              <Tooltip content="Минимальная доходность к погашению после уплаты НДФЛ. Позволяет отфильтровать низкодоходные бумаги.">
                <button type="button" className="opacity-60 hover:opacity-100">
                  <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <circle cx="12" cy="12" r="10" /><path d="M12 16v-4M12 8h.01" strokeWidth="2" strokeLinecap="round"/>
                  </svg>
                </button>
              </Tooltip>
            </div>
            <Input
              type="number"
              min={0}
              step={0.1}
              value={minYtm}
              onChange={(e) => setMinYtm(e.target.value === "" ? "" : Number(e.target.value))}
              placeholder="0"
              className="h-8 text-sm"
            />
          </div>

          {/* Max lot price */}
          <div className="space-y-1.5">
            <div className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
              Макс. стоимость лота, ₽
              <Tooltip content="Максимальная стоимость одного лота (цена × номинал × лотность). 0 — без ограничения.">
                <button type="button" className="opacity-60 hover:opacity-100">
                  <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <circle cx="12" cy="12" r="10" /><path d="M12 16v-4M12 8h.01" strokeWidth="2" strokeLinecap="round"/>
                  </svg>
                </button>
              </Tooltip>
            </div>
            <Input
              type="number"
              min={0}
              value={maxLotPrice}
              onChange={(e) => setMaxLotPrice(e.target.value === "" ? "" : Number(e.target.value))}
              placeholder="0 — без ограничения"
              className="h-8 text-sm"
            />
          </div>

          {/* Coupon type */}
          <div className="space-y-1.5">
            <div className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
              Тип купона
              <Tooltip content="Фиксированный — ставка не меняется. Плавающий — привязан к КС/RUONIA. Переменный — объявляется эмитентом.">
                <button type="button" className="opacity-60 hover:opacity-100">
                  <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <circle cx="12" cy="12" r="10" /><path d="M12 16v-4M12 8h.01" strokeWidth="2" strokeLinecap="round"/>
                  </svg>
                </button>
              </Tooltip>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {COUPON_TYPES.map((ct) => (
                <button
                  key={ct.value}
                  type="button"
                  onClick={() => toggleCouponType(ct.value)}
                  className={cn(
                    "rounded-full border px-2.5 py-0.5 text-xs transition-colors",
                    couponTypes.includes(ct.value)
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border hover:bg-muted/50",
                  )}
                >
                  {ct.label}
                </button>
              ))}
            </div>
          </div>

          {/* Risk level */}
          <div className="space-y-1.5">
            <div className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
              Уровень риска
              <Tooltip content="1 — Низкий (ОФЗ, госкорп), 2 — Умеренный (крупные частные), 3 — Высокий (BB и ниже). Можно выбрать несколько.">
                <button type="button" className="opacity-60 hover:opacity-100">
                  <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <circle cx="12" cy="12" r="10" /><path d="M12 16v-4M12 8h.01" strokeWidth="2" strokeLinecap="round"/>
                  </svg>
                </button>
              </Tooltip>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {RISK_LEVELS.map((rl) => (
                <button
                  key={rl.value}
                  type="button"
                  onClick={() => toggleRiskLevel(rl.value)}
                  className={cn(
                    "rounded-full border px-2.5 py-0.5 text-xs transition-colors",
                    riskLevels.includes(rl.value)
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border hover:bg-muted/50",
                  )}
                >
                  {rl.label}
                </button>
              ))}
            </div>
          </div>

          {/* Checkboxes */}
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 sm:col-span-2 lg:col-span-3">
            <label className="flex cursor-pointer items-center gap-2 text-sm">
              <Checkbox
                checked={hideDefault}
                onCheckedChange={(c) => setHideDefault(!!c)}
              />
              <span>
                Скрыть дефолтные
                <Tooltip content="Скрыть эмитентов, у которых MOEX зафиксировал дефолт или технический дефолт.">
                  <button type="button" className="ml-1 opacity-60 hover:opacity-100">
                    <svg className="inline h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <circle cx="12" cy="12" r="10" /><path d="M12 16v-4M12 8h.01" strokeWidth="2" strokeLinecap="round"/>
                    </svg>
                  </button>
                </Tooltip>
              </span>
            </label>
            <label className="flex cursor-pointer items-center gap-2 text-sm">
              <Checkbox
                checked={hideSubordinated}
                onCheckedChange={(c) => setHideSubordinated(!!c)}
              />
              <span>
                Скрыть субординированные
                <Tooltip content="Субординированные облигации при банкротстве выплачиваются последними после всех других кредиторов.">
                  <button type="button" className="ml-1 opacity-60 hover:opacity-100">
                    <svg className="inline h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <circle cx="12" cy="12" r="10" /><path d="M12 16v-4M12 8h.01" strokeWidth="2" strokeLinecap="round"/>
                    </svg>
                  </button>
                </Tooltip>
              </span>
            </label>
          </div>
        </CardContent>
      </Card>

      {/* Table toolbar */}
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          {isLoading ? "Загрузка…" : `${table.getFilteredRowModel().rows.length} бумаг`}
        </p>
        <PopoverRoot>
          <PopoverTrigger asChild>
            <Button variant="outline" size="sm" className="gap-1.5">
              <Settings2 className="h-4 w-4" />
              Колонки
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-56" align="end">
            <p className="mb-2 text-xs font-semibold text-muted-foreground">Видимость колонок</p>
            <div className="space-y-2">
              {table.getAllLeafColumns().filter((c) => c.getCanHide()).map((col) => (
                <label key={col.id} className="flex cursor-pointer items-center gap-2 text-sm">
                  <Checkbox
                    checked={col.getIsVisible()}
                    onCheckedChange={(v) => col.toggleVisibility(!!v)}
                  />
                  {typeof col.columnDef.header === "string" ? col.columnDef.header : col.id}
                </label>
              ))}
            </div>
          </PopoverContent>
        </PopoverRoot>
      </div>

      {/* Table */}
      <div className="overflow-hidden rounded-lg border border-border">
        {isLoading && (
          <div className="space-y-2 p-4">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        )}
        {isError && (
          <p className="p-6 text-sm text-destructive">
            Не удалось загрузить данные. Проверьте API.
          </p>
        )}
        {!isLoading && !isError && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/50">
                {table.getHeaderGroups().map((hg) => (
                  <tr key={hg.id}>
                    {hg.headers.map((header) => (
                      <th
                        key={header.id}
                        className="cursor-pointer select-none whitespace-nowrap px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider"
                        onClick={header.column.getToggleSortingHandler()}
                      >
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        {{ asc: " ↑", desc: " ↓" }[header.column.getIsSorted() as string] ?? null}
                      </th>
                    ))}
                  </tr>
                ))}
              </thead>
              <tbody>
                {table.getRowModel().rows.map((row) => (
                  <tr
                    key={row.id}
                    className="cursor-pointer border-t border-border hover:bg-muted/30"
                    onClick={() => setSelectedSecid(row.original.secid)}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <td key={cell.id} className="whitespace-nowrap px-4 py-2.5">
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            {table.getRowModel().rows.length === 0 && (
              <p className="p-8 text-center text-sm text-muted-foreground">
                Нет бумаг по заданным фильтрам
              </p>
            )}
          </div>
        )}
      </div>

      <BondDetailSheet secid={selectedSecid} onClose={() => setSelectedSecid(null)} />
    </div>
  );
}
