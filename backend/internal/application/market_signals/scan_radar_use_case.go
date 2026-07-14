package market_signals

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"time"

	appbonds "github.com/tonatos/bond-monitor/backend/internal/application/bonds"
	domain "github.com/tonatos/bond-monitor/backend/internal/domain/market_signals"
	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
	"github.com/tonatos/bond-monitor/backend/internal/domain/screening"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/persistence"
)

type ScanRadarUseCase struct {
	bondSvc         *appbonds.Service
	spreadSnapshots *persistence.SpreadSnapshotsRepository
	radarRepo       *persistence.MarketRadarRepository
	keyRatePP       float64
	taxRateFraction float64
}

func NewScanRadarUseCase(
	bondSvc *appbonds.Service,
	spreadSnapshots *persistence.SpreadSnapshotsRepository,
	radarRepo *persistence.MarketRadarRepository,
	keyRatePP, taxRateFraction float64,
) *ScanRadarUseCase {
	return &ScanRadarUseCase{
		bondSvc: bondSvc, spreadSnapshots: spreadSnapshots, radarRepo: radarRepo,
		keyRatePP: keyRatePP, taxRateFraction: taxRateFraction,
	}
}

func (u *ScanRadarUseCase) Run(ctx context.Context, today time.Time) error {
	if u.radarRepo == nil || u.spreadSnapshots == nil {
		return nil
	}
	universeAll := u.bondSvc.LoadUniverse().Bonds
	filtered := domain.FilterRadarUniverse(universeAll, domain.DefaultMarketRadarPolicy.Spread)

	scored := screening.ScoreBondsForProfile(
		filtered,
		screening.RiskProfileNormal,
		u.keyRatePP,
		u.taxRateFraction,
		screening.DefaultDurationPolicy,
	)
	scoresByISIN := make(map[string]float64, len(scored))
	for _, b := range scored {
		if b.Score != nil {
			scoresByISIN[b.ISIN] = *b.Score
		}
	}

	dateKey := persistence.DateKey(today)
	pastKey := persistence.DateKey(today.AddDate(0, 0, -7))
	todayByISIN := make(map[string]domain.BondSnapshot, len(filtered))
	isins := make([]string, 0, len(filtered))

	for _, bond := range filtered {
		spread := domain.CreditSpreadPP(bond, u.keyRatePP, u.taxRateFraction)
		if spread == nil {
			continue
		}
		var ord *int
		if bond.CreditRating != nil {
			if v, ok := bonds.RatingOrder[*bond.CreditRating]; ok {
				ord = &v
			}
		}
		_ = u.spreadSnapshots.Upsert(ctx, persistence.SpreadSnapshot{
			ISIN: bond.ISIN, Date: dateKey, CreditSpreadPP: *spread,
			LastPricePct: bond.LastPrice, Sector: bond.Sector, RatingOrdinal: ord,
		})
		todayByISIN[bond.ISIN] = domain.BondSnapshot{
			CreditSpreadPP: *spread,
			LastPricePct:   bond.LastPrice,
			Sector:         bond.Sector,
		}
		isins = append(isins, bond.ISIN)
	}

	pastRows, _ := u.spreadSnapshots.ListByISINsAndDate(ctx, isins, pastKey)
	pastByISIN := make(map[string]domain.BondSnapshot, len(pastRows))
	for isin, row := range pastRows {
		pastByISIN[isin] = domain.BondSnapshot{
			CreditSpreadPP: row.CreditSpreadPP,
			LastPricePct:   row.LastPricePct,
			Sector:         row.Sector,
		}
	}

	snap := domain.ScanMarketRadar(domain.ScanParams{
		Universe: filtered, TodayByISIN: todayByISIN, PastByISIN: pastByISIN,
		KeyRatePP: u.keyRatePP, TaxRateFraction: u.taxRateFraction,
		Policy: domain.DefaultMarketRadarPolicy, ScoresByISIN: scoresByISIN,
		ScannedAt: today,
	})

	payload, err := json.Marshal(radarPayloadFromSnapshot(snap))
	if err != nil {
		return err
	}
	return u.radarRepo.SaveRun(ctx, persistence.MarketRadarRun{
		ID:            newRadarRunID(),
		ScannedAt:     snap.ScannedAt.UTC().Format(time.RFC3339),
		UniverseCount: snap.UniverseScanned,
		PayloadJSON:   payload,
	})
}

func newRadarRunID() string {
	var b [8]byte
	_, _ = rand.Read(b[:])
	return "radar-" + hex.EncodeToString(b[:])
}

type storedRadarPayload struct {
	Sectors   []domain.SectorHeatmapRow   `json:"sectors"`
	Anomalies []domain.AnomalyCandidate   `json:"anomalies"`
	DipIdeas  []domain.DipIdea            `json:"dip_ideas"`
}

func radarPayloadFromSnapshot(s domain.RadarSnapshot) storedRadarPayload {
	return storedRadarPayload{
		Sectors: s.Sectors, Anomalies: s.Anomalies, DipIdeas: s.DipIdeas,
	}
}

// StoredRadarPayloadForTest exposes payload encoding for tests.
func StoredRadarPayloadForTest(s domain.RadarSnapshot) ([]byte, error) {
	return json.Marshal(radarPayloadFromSnapshot(s))
}

// PortfolioISINIndex maps ISIN to portfolio IDs from plan positions.
func PortfolioISINIndex(portfolios []portfolio.Portfolio) map[string][]string {
	out := map[string][]string{}
	for _, p := range portfolios {
		for _, pos := range p.Positions {
			if pos.ISIN == "" {
				continue
			}
			out[pos.ISIN] = appendUnique(out[pos.ISIN], p.ID)
		}
	}
	return out
}

func appendUnique(list []string, id string) []string {
	for _, v := range list {
		if v == id {
			return list
		}
	}
	return append(list, id)
}
