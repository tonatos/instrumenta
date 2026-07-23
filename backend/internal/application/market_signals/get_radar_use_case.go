package market_signals

import (
	"context"
	"encoding/json"

	appportfolio "github.com/tonatos/instrumenta/backend/internal/application/portfolio"
	"github.com/tonatos/instrumenta/backend/internal/infrastructure/persistence"
)

type RadarResponse struct {
	ScannedAt       string            `json:"scanned_at"`
	UniverseScanned int               `json:"universe_scanned"`
	Sectors         []RadarSectorRow  `json:"sectors"`
	Anomalies       []RadarAnomalyRow `json:"anomalies"`
	DipIdeas        []RadarDipIdeaRow `json:"dip_ideas"`
}

type RadarSectorRow struct {
	Sector       string   `json:"sector"`
	Change7dPct  float64  `json:"change_7d_pct"`
	AnomalyCount int      `json:"anomaly_count"`
	DipIdeaCount int      `json:"dip_idea_count"`
	BondCount    int      `json:"bond_count"`
	InPortfolios []string `json:"in_portfolios,omitempty"`
}

type RadarAnomalyRow struct {
	ISIN             string   `json:"isin"`
	Secid            string   `json:"secid"`
	Name             string   `json:"name"`
	Sector           string   `json:"sector"`
	SpreadPP         float64  `json:"spread_pp"`
	ExpectedSpreadPP float64  `json:"expected_spread_pp"`
	DeltaPP          float64  `json:"delta_pp"`
	ZScore           *float64 `json:"z_score,omitempty"`
	Peers            int      `json:"peers"`
	InPortfolios     []string `json:"in_portfolios,omitempty"`
}

type RadarDipIdeaRow struct {
	ISIN                     string   `json:"isin"`
	Secid                    string   `json:"secid"`
	Name                     string   `json:"name"`
	Sector                   string   `json:"sector"`
	BondChange7dPct          float64  `json:"bond_change_7d_pct"`
	SectorChange7dPct        float64  `json:"sector_change_7d_pct"`
	IdiosyncraticExcess7dPct float64  `json:"idiosyncratic_excess_pct"`
	Score                    float64  `json:"score"`
	Interpretation           string   `json:"interpretation"`
	InPortfolios             []string `json:"in_portfolios,omitempty"`
}

type GetRadarUseCase struct {
	radarRepo  *persistence.MarketRadarRepository
	portfolios *appportfolio.Service
}

func NewGetRadarUseCase(radarRepo *persistence.MarketRadarRepository, portfolios *appportfolio.Service) *GetRadarUseCase {
	return &GetRadarUseCase{radarRepo: radarRepo, portfolios: portfolios}
}

func (u *GetRadarUseCase) Get(ctx context.Context, highlightPortfolios bool) (*RadarResponse, error) {
	if u.radarRepo == nil {
		return emptyRadarResponse(), nil
	}
	run, err := u.radarRepo.GetLatest(ctx)
	if err != nil || run == nil {
		return emptyRadarResponse(), err
	}
	var payload storedRadarPayload
	if err := json.Unmarshal(run.PayloadJSON, &payload); err != nil {
		return nil, err
	}

	var isinIndex map[string][]string
	sectorPortfolios := map[string][]string{}
	if highlightPortfolios && u.portfolios != nil {
		all, err := u.portfolios.ListPortfolios(ctx)
		if err != nil {
			return nil, err
		}
		isinIndex = PortfolioISINIndex(all)
		for isin, ids := range isinIndex {
			for _, a := range payload.Anomalies {
				if a.ISIN == isin {
					for _, id := range ids {
						sectorPortfolios[a.Sector] = appendUnique(sectorPortfolios[a.Sector], id)
					}
				}
			}
			for _, d := range payload.DipIdeas {
				if d.ISIN == isin {
					for _, id := range ids {
						sectorPortfolios[d.Sector] = appendUnique(sectorPortfolios[d.Sector], id)
					}
				}
			}
		}
	}

	resp := &RadarResponse{
		ScannedAt:       run.ScannedAt,
		UniverseScanned: run.UniverseCount,
	}
	for _, s := range payload.Sectors {
		row := RadarSectorRow{
			Sector: s.Sector, Change7dPct: s.Change7dPct,
			AnomalyCount: s.AnomalyCount, DipIdeaCount: s.DipIdeaCount, BondCount: s.BondCount,
		}
		if ids, ok := sectorPortfolios[s.Sector]; ok {
			row.InPortfolios = ids
		}
		resp.Sectors = append(resp.Sectors, row)
	}
	for _, a := range payload.Anomalies {
		row := RadarAnomalyRow{
			ISIN: a.ISIN, Secid: a.Secid, Name: a.Name, Sector: a.Sector,
			SpreadPP: a.SpreadPP, ExpectedSpreadPP: a.ExpectedSpreadPP,
			DeltaPP: a.DeltaPP, ZScore: a.ZScore, Peers: a.Peers,
		}
		if isinIndex != nil {
			row.InPortfolios = isinIndex[a.ISIN]
		}
		resp.Anomalies = append(resp.Anomalies, row)
	}
	for _, d := range payload.DipIdeas {
		row := RadarDipIdeaRow{
			ISIN: d.ISIN, Secid: d.Secid, Name: d.Name, Sector: d.Sector,
			BondChange7dPct: d.BondChange7dPct, SectorChange7dPct: d.SectorChange7dPct,
			IdiosyncraticExcess7dPct: d.IdiosyncraticExcess7dPct,
			Score: d.Score, Interpretation: d.Interpretation,
		}
		if isinIndex != nil {
			row.InPortfolios = isinIndex[d.ISIN]
		}
		resp.DipIdeas = append(resp.DipIdeas, row)
	}
	return resp, nil
}

func emptyRadarResponse() *RadarResponse {
	return &RadarResponse{
		Sectors: []RadarSectorRow{}, Anomalies: []RadarAnomalyRow{}, DipIdeas: []RadarDipIdeaRow{},
	}
}
