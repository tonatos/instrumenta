import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
  type VisibilityState,
  type SortingState,
} from "@tanstack/react-table";
import {
  ChevronDown,
  ChevronUp,
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
import {
  getScreenerRiskProfile,
  setScreenerRiskProfile,
  subscribeScreenerRiskProfile,
  type ScreenerRiskProfile,
} from "@/features/screener/screenerRiskProfile";
import { buildScreenerQueryParams } from "@/features/screener/screenerQuery";
import { useDebouncedValue } from "@/features/screener/useDebouncedValue";
import { RISK_LABELS as PROFILE_RISK_LABELS } from "@/features/portfolio/labels";
import { useRateScenario } from "@/features/settings/RateScenarioProvider";
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

const MOBILE_HIDDEN_COLUMNS: VisibilityState = {
  duration_years: false,
  ytm: false,
  coupon_rate: false,
  coupon_type: false,
  risk_level: false,
  lot_price: false,
  credit_rating: false,
  volume_rub: false,
  maturity_date: false,
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
  const [searchInput, setSearchInput] = useState("");
  const searchQuery = useDebouncedValue(searchInput, 300);
  const loadMoreRef = useRef<HTMLDivElement | null>(null);
  const [selectedSecid, setSelectedSecid] = useState<string | null>(null);
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>(
    loadColumnVisibility,
  );
  const [filtersExpanded, setFiltersExpanded] = useState(false);
  const [isMobileViewport, setIsMobileViewport] = useState(false);
  const queryClient = useQueryClient();
  const { rateScenario } = useRateScenario();
  const [riskProfile, setRiskProfile] = useState<ScreenerRiskProfile>(getScreenerRiskProfile);

  useEffect(() => subscribeScreenerRiskProfile(() => setRiskProfile(getScreenerRiskProfile())), []);

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 767px)");
    const syncViewport = () => {
      const mobile = mq.matches;
      setIsMobileViewport(mobile);
      setFiltersExpanded(!mobile);
      if (mobile) {
        setColumnVisibility((prev) => ({ ...prev, ...MOBILE_HIDDEN_COLUMNS }));
      } else {
        setColumnVisibility(loadColumnVisibility());
      }
    };
    syncViewport();
    mq.addEventListener("change", syncViewport);
    return () => mq.removeEventListener("change", syncViewport);
  }, []);

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

  const debouncedMaxDays = useDebouncedValue(maxDays, 300);
  const debouncedMinVolume = useDebouncedValue(minVolume, 300);
  const debouncedMinYtm = useDebouncedValue(minYtm, 300);
  const debouncedMaxLotPrice = useDebouncedValue(maxLotPrice, 300);

  const queryParams = useMemo(
    () =>
      buildScreenerQueryParams({
        filterBy,
        maxDays: debouncedMaxDays,
        minVolume: debouncedMinVolume,
        minYtm: debouncedMinYtm,
        maxLotPrice: debouncedMaxLotPrice,
        couponTypes,
        riskLevels,
        hideDefault,
        hideSubordinated,
        search: searchQuery,
        sorting,
        riskProfile,
      }),
    [
      filterBy,
      debouncedMaxDays,
      debouncedMinVolume,
      debouncedMinYtm,
      debouncedMaxLotPrice,
      couponTypes,
      riskLevels,
      hideDefault,
      hideSubordinated,
      searchQuery,
      sorting,
      riskProfile,
    ],
  );

  const {
    data,
    isLoading,
    isError,
    refetch,
    isFetching,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: ["bonds", queryParams, rateScenario],
    queryFn: ({ pageParam }) => api.getBonds({ ...queryParams, page: pageParam }, riskProfile),
    initialPageParam: 1,
    getNextPageParam: (last) =>
      last.page * last.page_size < last.total ? last.page + 1 : undefined,
  });

  const bonds = useMemo(() => data?.pages.flatMap((page) => page.bonds) ?? [], [data]);
  const total = data?.pages[0]?.total ?? 0;
  const source = data?.pages[0]?.source ?? "";

  useEffect(() => {
    const node = loadMoreRef.current;
    if (!node || !hasNextPage) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && hasNextPage && !isFetchingNextPage) {
          void fetchNextPage();
        }
      },
      { rootMargin: "200px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [fetchNextPage, hasNextPage, isFetchingNextPage, bonds.length]);

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
    setSearchInput("");
  }, [config]);

  const activeFilterCount = useMemo(() => {
    let count = 0;
    if (searchInput.trim()) count++;
    if (filterBy !== "effective") count++;
    if (maxDays !== "" && maxDays !== (config?.max_days ?? "")) count++;
    if (minVolume !== "" && minVolume !== (config?.min_volume_rub ?? "")) count++;
    if (minYtm !== "") count++;
    if (maxLotPrice !== "" && maxLotPrice !== 0) count++;
    if (couponTypes.length > 0) count++;
    if (riskLevels.length > 0) count++;
    if (hideSubordinated) count++;
    if (!hideDefault) count++;
    return count;
  }, [
    searchInput,
    filterBy,
    maxDays,
    minVolume,
    minYtm,
    maxLotPrice,
    couponTypes,
    riskLevels,
    hideSubordinated,
    hideDefault,
    config,
  ]);

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
        enableSorting: true,
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
        enableSorting: true,
        cell: (i) => i.getValue() ?? "—",
      }),
      columnHelper.accessor("duration_years", {
        id: "duration_years",
        header: "Дюрация",
        enableSorting: false,
        cell: (i) => {
          const v = i.getValue();
          return v != null ? `${v.toFixed(1)} г` : "—";
        },
      }),
      columnHelper.accessor("ytm_net", {
        header: "YTM нетто",
        enableSorting: true,
        cell: (i) => formatPct(i.getValue()),
      }),
      columnHelper.accessor("ytm", {
        id: "ytm",
        header: "YTM брутто",
        enableSorting: false,
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
        enableSorting: true,
        cell: (i) => (
          <Badge variant={i.getValue() != null && i.getValue()! >= 60 ? "default" : "secondary"}>
            {i.getValue()?.toFixed(0) ?? "—"}
          </Badge>
        ),
      }),
      columnHelper.accessor((b) => b.prev_volume_rub ?? b.volume_rub, {
        id: "volume_rub",
        header: "Объём",
        enableSorting: true,
        cell: ({ row }) => {
          const bond = row.original;
          const yesterday = bond.prev_volume_rub;
          const today = bond.volume_rub;
          const main = yesterday ?? today;
          if (main == null) return "—";
          return (
            <div className="flex flex-col items-end leading-tight">
              <span>{formatRub(main)}</span>
              {yesterday != null && today != null && (
                <span className="text-[10px] font-normal text-muted-foreground">
                  {formatRub(today)}
                </span>
              )}
            </div>
          );
        },
      }),
      columnHelper.accessor("maturity_date", {
        header: "Погашение",
        cell: (i) => formatDate(i.getValue()),
      }),
    ],
    [toggleFavorite],
  );

  const table = useReactTable({
    data: bonds,
    columns,
    state: { sorting, columnVisibility },
    onSortingChange: setSorting,
    onColumnVisibilityChange: (updater) => {
      const next =
        typeof updater === "function"
          ? (updater as (old: VisibilityState) => VisibilityState)(columnVisibility)
          : updater;
      handleColumnVisibility(next);
    },
    getCoreRowModel: getCoreRowModel(),
    manualSorting: true,
  });

  const visibleColumnCount = table.getVisibleLeafColumns().length;

  const exportCsv = async () => {
    const exportParams = buildScreenerQueryParams({
      filterBy,
      maxDays,
      minVolume,
      minYtm,
      maxLotPrice,
      couponTypes,
      riskLevels,
      hideDefault,
      hideSubordinated,
      search: searchQuery,
      sorting,
      riskProfile,
      exportAll: true,
    });
    const exported = await api.getBonds(exportParams, riskProfile);
    if (!exported.bonds.length) return;
    const header = ["secid", "isin", "name", "ytm_net", "score", "rating", "days", "coupon_type", "risk_level"];
    const rows = exported.bonds.map((b) =>
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
            {isLoading
              ? "Загрузка…"
              : `${bonds.length} из ${total}${source ? ` · ${source}` : ""}`}
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
          <div className="flex items-center justify-between gap-2">
            <button
              type="button"
              className="flex min-w-0 flex-1 items-center gap-2 text-left md:pointer-events-none"
              onClick={() => setFiltersExpanded((v) => !v)}
              data-testid="screener-filters-toggle"
              aria-expanded={filtersExpanded}
            >
              <CardTitle className="text-sm font-semibold">Фильтры</CardTitle>
              {!filtersExpanded && activeFilterCount > 0 && (
                <Badge variant="secondary" className="text-xs">
                  {activeFilterCount} активн.
                </Badge>
              )}
              <span className="md:hidden">
                {filtersExpanded ? (
                  <ChevronUp className="h-4 w-4 text-muted-foreground" aria-hidden />
                ) : (
                  <ChevronDown className="h-4 w-4 text-muted-foreground" aria-hidden />
                )}
              </span>
            </button>
            <Button variant="ghost" size="sm" onClick={resetFilters} className="h-7 shrink-0 gap-1 text-xs">
              <RotateCcw className="h-3.5 w-3.5" />
              Сбросить
            </Button>
          </div>
        </CardHeader>
        {filtersExpanded && (
        <CardContent className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {/* Search */}
          <div className="space-y-1 sm:col-span-2 lg:col-span-3">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                className="pl-9"
                placeholder="Поиск по названию, SECID или ISIN…"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
              />
            </div>
          </div>

          {/* Risk profile */}
          <div className="space-y-1.5">
            <div className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
              Риск-профиль
              <Tooltip content="Скор и ранжирование рассчитываются под выбранную стратегию: консервативный, нормальный или агрессивный.">
                <button type="button" className="opacity-60 hover:opacity-100">
                  <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <circle cx="12" cy="12" r="10" /><path d="M12 16v-4M12 8h.01" strokeWidth="2" strokeLinecap="round"/>
                  </svg>
                </button>
              </Tooltip>
            </div>
            <select
              aria-label="Риск-профиль"
              className="flex h-8 w-full rounded-md border border-border bg-card px-2 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
              value={riskProfile}
              onChange={(e) => {
                const value = e.target.value as ScreenerRiskProfile;
                setScreenerRiskProfile(value);
                setRiskProfile(value);
              }}
            >
              {(Object.keys(PROFILE_RISK_LABELS) as ScreenerRiskProfile[]).map((profile) => (
                <option key={profile} value={profile}>
                  {PROFILE_RISK_LABELS[profile]}
                </option>
              ))}
            </select>
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
            <div className="flex flex-col gap-2 sm:flex-row">
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
                  {v === "effective" ? (
                    <>
                      <span className="sm:hidden">Оферта/погаш.</span>
                      <span className="hidden sm:inline">До оферты/погашения</span>
                    </>
                  ) : (
                    "До погашения"
                  )}
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
              <Tooltip content="Минимальный объём торгов за предыдущую сессию — по нему же фильтруется скринер. В таблице крупно показан вчерашний объём, мелко — сегодняшний.">
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
        )}
      </Card>

      {/* Table toolbar */}
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          {isLoading ? "Загрузка…" : `${bonds.length} из ${total} бумаг`}
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
                        className={cn(
                          "whitespace-nowrap px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider",
                          header.column.getCanSort() && "cursor-pointer select-none",
                          (header.column.id === "favorite" || header.column.id === "name") &&
                            "sticky left-0 z-10 bg-muted/95 shadow-[2px_0_4px_-2px_rgba(0,0,0,0.08)]",
                        )}
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
                      <td
                        key={cell.id}
                        className={cn(
                          "whitespace-nowrap px-4 py-2.5",
                          (cell.column.id === "favorite" || cell.column.id === "name") &&
                            "sticky left-0 z-[1] bg-background shadow-[2px_0_4px_-2px_rgba(0,0,0,0.06)]",
                        )}
                      >
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
            {hasNextPage && (
              <div ref={loadMoreRef} data-testid="screener-load-more" className="flex justify-center p-4">
                {isFetchingNextPage ? (
                  <span className="text-sm text-muted-foreground">Загрузка…</span>
                ) : (
                  <span className="text-xs text-muted-foreground">Прокрутите для подгрузки</span>
                )}
              </div>
            )}
            {isMobileViewport && visibleColumnCount > 4 && (
              <p className="border-t border-border px-4 py-2 text-center text-xs text-muted-foreground md:hidden">
                Свайп влево для остальных колонок
              </p>
            )}
          </div>
        )}
      </div>

      <BondDetailSheet
        secid={selectedSecid}
        riskProfile={riskProfile}
        onClose={() => setSelectedSecid(null)}
      />
    </div>
  );
}
