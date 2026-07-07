import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { formatRub } from "@/lib/utils";

interface SettingsSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function SettingsSheet({ open, onOpenChange }: SettingsSheetProps) {
  const { data, isLoading, refetch } = useQuery({
    queryKey: ["config"],
    queryFn: api.getConfig,
    enabled: open,
  });

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right">
        <SheetHeader>
          <SheetTitle>Настройки</SheetTitle>
        </SheetHeader>
        <div className="space-y-4">
          {isLoading && <Skeleton className="h-32 w-full" />}
          {data && (
            <dl className="space-y-3 text-sm">
              <div className="flex justify-between">
                <dt className="text-muted-foreground">Ключевая ставка</dt>
                <dd>{data.key_rate}%</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-muted-foreground">НДФЛ</dt>
                <dd>{data.tax_rate}%</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-muted-foreground">Макс. срок</dt>
                <dd>{data.max_days} дн.</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-muted-foreground">Мин. объём</dt>
                <dd>{formatRub(data.min_volume_rub)}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-muted-foreground">T-Invest (read)</dt>
                <dd>{data.tinkoff_configured ? "✓" : "—"}</dd>
              </div>
            </dl>
          )}
          <p className="text-xs text-muted-foreground">
            Параметры задаются через переменные окружения (.env). Перезапустите API после изменений.
          </p>
          <div className="flex flex-col gap-2">
            <Button variant="outline" onClick={() => api.refreshBonds().then(() => refetch())}>
              Обновить данные MOEX
            </Button>
            <Button variant="outline" onClick={() => api.refreshRatings()}>
              Обновить рейтинги
            </Button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
