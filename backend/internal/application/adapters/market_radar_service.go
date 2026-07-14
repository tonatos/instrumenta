package adapters

import (
	"context"

	"github.com/tonatos/bond-monitor/backend/internal/application"
	appmarketsignals "github.com/tonatos/bond-monitor/backend/internal/application/market_signals"
)

type MarketRadarService struct {
	inner *appmarketsignals.GetRadarUseCase
}

func NewMarketRadarService(inner *appmarketsignals.GetRadarUseCase) *MarketRadarService {
	return &MarketRadarService{inner: inner}
}

func (s *MarketRadarService) GetMarketRadar(ctx context.Context, highlightPortfolios bool) (*application.MarketRadarResponse, error) {
	if s.inner == nil {
		return &application.MarketRadarResponse{
			Sectors:   []application.MarketRadarSectorRow{},
			Anomalies: []application.MarketRadarAnomalyRow{},
			DipIdeas:  []application.MarketRadarDipIdeaRow{},
		}, nil
	}
	resp, err := s.inner.Get(ctx, highlightPortfolios)
	if err != nil || resp == nil {
		return nil, err
	}
	return toApplicationRadar(resp), nil
}

func toApplicationRadar(resp *appmarketsignals.RadarResponse) *application.MarketRadarResponse {
	out := &application.MarketRadarResponse{
		ScannedAt:       resp.ScannedAt,
		UniverseScanned: resp.UniverseScanned,
		Sectors:         make([]application.MarketRadarSectorRow, 0, len(resp.Sectors)),
		Anomalies:       make([]application.MarketRadarAnomalyRow, 0, len(resp.Anomalies)),
		DipIdeas:        make([]application.MarketRadarDipIdeaRow, 0, len(resp.DipIdeas)),
	}
	for _, s := range resp.Sectors {
		out.Sectors = append(out.Sectors, application.MarketRadarSectorRow{
			Sector: s.Sector, Change7dPct: s.Change7dPct,
			AnomalyCount: s.AnomalyCount, DipIdeaCount: s.DipIdeaCount, BondCount: s.BondCount,
			InPortfolios: s.InPortfolios,
		})
	}
	for _, a := range resp.Anomalies {
		out.Anomalies = append(out.Anomalies, application.MarketRadarAnomalyRow{
			ISIN: a.ISIN, Secid: a.Secid, Name: a.Name, Sector: a.Sector,
			SpreadPP: a.SpreadPP, ExpectedSpreadPP: a.ExpectedSpreadPP,
			DeltaPP: a.DeltaPP, ZScore: a.ZScore, Peers: a.Peers,
			InPortfolios: a.InPortfolios,
		})
	}
	for _, d := range resp.DipIdeas {
		out.DipIdeas = append(out.DipIdeas, application.MarketRadarDipIdeaRow{
			ISIN: d.ISIN, Secid: d.Secid, Name: d.Name, Sector: d.Sector,
			BondChange7dPct: d.BondChange7dPct, SectorChange7dPct: d.SectorChange7dPct,
			IdiosyncraticExcess7dPct: d.IdiosyncraticExcess7dPct,
			Score: d.Score, Interpretation: d.Interpretation,
			InPortfolios: d.InPortfolios,
		})
	}
	return out
}
