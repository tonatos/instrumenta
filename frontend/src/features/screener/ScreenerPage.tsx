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
import { Download, RefreshCw, Settings2, Star } from "lucide-react";
import { api } from "@/api/client";
import type { Bond } from "@/api/types";
import { BondDetailSheet } from "@/features/screener/BondDetailSheet";
import { ScreenerFilters } from "@/features/screener/ScreenerFilters";
import {
  getScreenerRiskProfile,
  setScreenerRiskProfile,
  subscribeScreenerRiskProfile,
  type ScreenerRiskProfile,
} from "@/features/screener/screenerRiskProfile";
import { buildScreenerQueryParams } from "@/features/screener/screenerQuery";
import { useDebouncedValue } from "@/features/screener/useDebouncedValue";
import { useRateScenario } from "@/features/settings/RateScenarioProvider";
import { RISK_LABELS as PROFILE_RISK_LABELS } from "@/features/portfolio/labels";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { PopoverContent, PopoverRoot, PopoverTrigger } from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, formatDate, formatPct, formatRub } from "@/lib/utils";

const columnHelper = createColumnHelper<Bond>();

const RISK_LABELS: Record<number, string> = {
  0: "Неизвестен",
  1: "Низкий",
  2: "Умеренный",
  3: "Высокий",
};

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
  const [advancedFiltersOpen, setAdvancedFiltersOpen] = useState(false);
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
  const [sectors, setSectors] = useState<string[]>([]);
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
        sectors,
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
      sectors,
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
    setSectors([]);
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
    if (sectors.length > 0) count++;
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
    sectors,
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
      sectors,
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

      <ScreenerFilters
        filtersExpanded={filtersExpanded}
        onToggleExpanded={() => setFiltersExpanded((v) => !v)}
        activeFilterCount={activeFilterCount}
        onReset={resetFilters}
        searchInput={searchInput}
        onSearchChange={setSearchInput}
        filterBy={filterBy}
        onFilterByChange={setFilterBy}
        maxDays={maxDays}
        onMaxDaysChange={setMaxDays}
        minVolume={minVolume}
        onMinVolumeChange={setMinVolume}
        defaultMinVolume={config?.min_volume_rub ?? 0}
        minYtm={minYtm}
        onMinYtmChange={setMinYtm}
        maxLotPrice={maxLotPrice}
        onMaxLotPriceChange={setMaxLotPrice}
        couponTypes={couponTypes}
        onCouponTypesChange={setCouponTypes}
        riskLevels={riskLevels}
        onRiskLevelsChange={setRiskLevels}
        sectors={sectors}
        onSectorsChange={setSectors}
        hideDefault={hideDefault}
        onHideDefaultChange={setHideDefault}
        hideSubordinated={hideSubordinated}
        onHideSubordinatedChange={setHideSubordinated}
        advancedOpen={advancedFiltersOpen}
        onAdvancedOpenChange={setAdvancedFiltersOpen}
      />

      {/* Table toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          {isLoading ? "Загрузка…" : `${bonds.length} из ${total} бумаг`}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <select
            aria-label="Риск-профиль"
            data-testid="screener-risk-profile"
            className="flex h-9 min-h-10 max-w-[11rem] rounded-md border border-border bg-card px-2.5 text-sm shadow-sm focus:outline-none focus:ring-1 focus:ring-ring sm:min-h-9"
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
          <PopoverRoot>
            <PopoverTrigger asChild>
              <Button variant="outline" size="sm" className="h-9 min-h-10 gap-1.5 sm:min-h-9">
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
