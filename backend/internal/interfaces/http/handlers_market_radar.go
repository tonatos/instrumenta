package httpapi

import (
	"net/http"
	"strings"

	"github.com/tonatos/bond-monitor/backend/internal/application"
)

func (h *Handler) GetMarketRadar(w http.ResponseWriter, r *http.Request) {
	highlight := true
	if v := strings.TrimSpace(r.URL.Query().Get("highlight_portfolios")); v == "false" {
		highlight = false
	}
	if h.deps.MarketRadar == nil {
		WriteJSON(w, http.StatusOK, MarketRadarResponse{
			Sectors: []MarketRadarSectorRow{}, Anomalies: []MarketRadarAnomalyRow{}, DipIdeas: []MarketRadarDipIdeaRow{},
		})
		return
	}
	resp, err := h.deps.MarketRadar.GetMarketRadar(r.Context(), highlight)
	if err != nil {
		WriteError(w, http.StatusInternalServerError, err.Error(), nil)
		return
	}
	WriteJSON(w, http.StatusOK, marketRadarToResponse(resp))
}

func marketRadarToResponse(resp *application.MarketRadarResponse) MarketRadarResponse {
	if resp == nil {
		return MarketRadarResponse{
			Sectors: []MarketRadarSectorRow{}, Anomalies: []MarketRadarAnomalyRow{}, DipIdeas: []MarketRadarDipIdeaRow{},
		}
	}
	out := MarketRadarResponse{
		ScannedAt:       resp.ScannedAt,
		UniverseScanned: resp.UniverseScanned,
		Sectors:         make([]MarketRadarSectorRow, 0, len(resp.Sectors)),
		Anomalies:       make([]MarketRadarAnomalyRow, 0, len(resp.Anomalies)),
		DipIdeas:        make([]MarketRadarDipIdeaRow, 0, len(resp.DipIdeas)),
	}
	for _, s := range resp.Sectors {
		out.Sectors = append(out.Sectors, MarketRadarSectorRow{
			Sector: s.Sector, Change7dPct: s.Change7dPct,
			AnomalyCount: s.AnomalyCount, DipIdeaCount: s.DipIdeaCount, BondCount: s.BondCount,
			InPortfolios: s.InPortfolios,
		})
	}
	for _, a := range resp.Anomalies {
		out.Anomalies = append(out.Anomalies, MarketRadarAnomalyRow{
			ISIN: a.ISIN, Secid: a.Secid, Name: a.Name, Sector: a.Sector,
			SpreadPP: a.SpreadPP, ExpectedSpreadPP: a.ExpectedSpreadPP,
			DeltaPP: a.DeltaPP, ZScore: a.ZScore, Peers: a.Peers,
			InPortfolios: a.InPortfolios,
		})
	}
	for _, d := range resp.DipIdeas {
		out.DipIdeas = append(out.DipIdeas, MarketRadarDipIdeaRow{
			ISIN: d.ISIN, Secid: d.Secid, Name: d.Name, Sector: d.Sector,
			BondChange7dPct: d.BondChange7dPct, SectorChange7dPct: d.SectorChange7dPct,
			IdiosyncraticExcess7dPct: d.IdiosyncraticExcess7dPct,
			Score: d.Score, Interpretation: d.Interpretation,
			InPortfolios: d.InPortfolios,
		})
	}
	return out
}
