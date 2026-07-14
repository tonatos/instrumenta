import { Link, useNavigate } from "react-router-dom";
import { ExternalLink } from "lucide-react";
import type { Portfolio } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  SelectContent,
  SelectItem,
  SelectRoot,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { sectorLabel } from "@/features/bonds/sectorLabels";
import type { MarketRadarDipIdeaRow } from "@/features/radar/useMarketRadar";
import { cn, formatPct } from "@/lib/utils";

function portfolioLink(portfolioId: string) {
  return `/portfolio/${portfolioId}`;
}

function DipIdeaActions({
  idea,
  portfolios,
  fallbackPortfolioId,
}: {
  idea: MarketRadarDipIdeaRow;
  portfolios: Portfolio[];
  fallbackPortfolioId: string | null;
}) {
  const navigate = useNavigate();
  const ownedIds = idea.in_portfolios ?? [];
  const ownedPortfolios = portfolios.filter((p) => ownedIds.includes(p.id));

  if (ownedPortfolios.length === 1) {
    return (
      <Button asChild size="sm" variant="secondary" data-testid={`radar-open-portfolio-${idea.secid}`}>
        <Link to={portfolioLink(ownedPortfolios[0].id)}>Открыть в портфеле</Link>
      </Button>
    );
  }

  if (ownedPortfolios.length > 1) {
    return (
      <SelectRoot
        onValueChange={(value) => navigate(portfolioLink(value))}
      >
        <SelectTrigger
          className="h-8 w-full sm:w-[180px]"
          data-testid={`radar-open-portfolio-${idea.secid}`}
        >
          <SelectValue placeholder="Открыть в портфеле" />
        </SelectTrigger>
        <SelectContent>
          {ownedPortfolios.map((p) => (
            <SelectItem key={p.id} value={p.id}>
              {p.name}
            </SelectItem>
          ))}
        </SelectContent>
      </SelectRoot>
    );
  }

  return (
    <div className="flex flex-wrap gap-2">
      <Button asChild size="sm" variant="secondary">
        <Link to={`/?q=${encodeURIComponent(idea.secid)}`}>Скринер</Link>
      </Button>
      {fallbackPortfolioId && (
        <Button asChild size="sm" variant="outline">
          <Link to={portfolioLink(fallbackPortfolioId)}>Перейти в портфель</Link>
        </Button>
      )}
    </div>
  );
}

export function DipIdeasPanel({
  dipIdeas,
  portfolios,
  fallbackPortfolioId,
}: {
  dipIdeas: MarketRadarDipIdeaRow[];
  portfolios: Portfolio[];
  fallbackPortfolioId: string | null;
}) {
  if (dipIdeas.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground" data-testid="radar-dip-ideas-empty">
        Идей на просадке нет
      </p>
    );
  }

  return (
    <div className="space-y-3" data-testid="radar-dip-ideas">
      {dipIdeas.map((idea) => {
        const inPortfolio = (idea.in_portfolios?.length ?? 0) > 0;
        return (
          <div
            key={idea.isin}
            data-testid={`radar-dip-${idea.secid}`}
            className={cn(
              "space-y-3 rounded-lg border border-border/60 bg-card/50 p-3",
              inPortfolio ? "border-sky-400/40 bg-sky-500/5" : "border-sky-500/20 bg-sky-500/5",
            )}
          >
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <p className="font-medium">{idea.name}</p>
                  {inPortfolio && (
                    <Badge variant="outline" className="border-sky-400/50 text-sky-800 dark:text-sky-200">
                      В портфеле
                    </Badge>
                  )}
                </div>
                <p className="text-xs text-muted-foreground">
                  {sectorLabel(idea.sector)} · {idea.secid}
                </p>
              </div>
              <Badge className="bg-sky-500/15 font-mono text-sky-900 dark:text-sky-200">
                {Math.round(idea.score)}
              </Badge>
            </div>

            <div className="grid grid-cols-1 gap-2 text-xs sm:grid-cols-3">
              <div>
                <p className="text-muted-foreground">Δ7д бумаги</p>
                <p className="font-mono tabular-nums">{formatPct(idea.bond_change_7d_pct, 1)}</p>
              </div>
              <div>
                <p className="text-muted-foreground">Δ7д сектора</p>
                <p className="font-mono tabular-nums">{formatPct(idea.sector_change_7d_pct, 1)}</p>
              </div>
              <div>
                <p className="text-muted-foreground">Excess</p>
                <p className="font-mono tabular-nums">{formatPct(idea.idiosyncratic_excess_pct, 1)}</p>
              </div>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2">
              <DipIdeaActions
                idea={idea}
                portfolios={portfolios}
                fallbackPortfolioId={fallbackPortfolioId}
              />
              <Link
                to={`/?q=${encodeURIComponent(idea.secid)}`}
                className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              >
                <ExternalLink className="h-3 w-3" />
                Карточка
              </Link>
            </div>
          </div>
        );
      })}
    </div>
  );
}
