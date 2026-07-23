package notifications

import (
	"encoding/json"
	"os"
	"path/filepath"
	"time"

	"github.com/tonatos/instrumenta/backend/internal/domain/bonds"
	"github.com/tonatos/instrumenta/backend/internal/domain/portfolio"
	"github.com/tonatos/instrumenta/backend/internal/domain/shared"
	"github.com/tonatos/instrumenta/backend/internal/infrastructure/paths"
)

const devOverridesFilename = "dev_notification_overrides.json"

// DevOverridesPath returns the default path for dev notification overrides.
func DevOverridesPath() string {
	return filepath.Join(paths.CacheDir(), devOverridesFilename)
}

type devPutOfferOverride struct {
	OfferDate        string  `json:"offer_date"`
	SubmissionStart  string  `json:"submission_start"`
	SubmissionEnd    string  `json:"submission_end"`
	OfferPricePct    float64 `json:"offer_price_pct"`
}

type devOverridesFile struct {
	PortfolioID   string                           `json:"portfolio_id"`
	PutOffers     map[string]devPutOfferOverride   `json:"put_offers"`
	RiskBaselines map[string]riskSnapshotJSON      `json:"risk_baselines"`
	BondRisk      map[string]map[string]any        `json:"bond_risk"`
}

type riskSnapshotJSON struct {
	HasDefault          bool    `json:"has_default"`
	HasTechnicalDefault bool    `json:"has_technical_default"`
	CreditRating        *string `json:"credit_rating"`
}

type DevOverrides struct {
	PortfolioID   string
	PutOffers     map[string]devPutOfferOverride
	RiskBaselines map[string]portfolio.RiskSnapshot
	BondRisk      map[string]map[string]any
}

// BuildPutOfferOverrides returns fake put-offer data with an open submission window.
func BuildPutOfferOverrides(portfolioID, isin string, today time.Time) map[string]any {
	ref := shared.DateOnly(today)
	offerDate := shared.AddDays(ref, 10)
	return map[string]any{
		"portfolio_id": portfolioID,
		"put_offers": map[string]any{
			isin: map[string]any{
				"offer_date":        shared.FormatISODate(offerDate),
				"submission_start":  shared.FormatISODate(shared.AddDays(ref, -1)),
				"submission_end":    shared.FormatISODate(shared.AddDays(ref, 7)),
				"offer_price_pct":   100.0,
			},
		},
		"risk_baselines": map[string]any{},
		"bond_risk":      map[string]any{},
	}
}

// BuildRiskDefaultOverrides returns fake data that triggers a critical default escalation.
func BuildRiskDefaultOverrides(portfolioID, isin string) map[string]any {
	rating := "ruBBB"
	return map[string]any{
		"portfolio_id": portfolioID,
		"put_offers":   map[string]any{},
		"risk_baselines": map[string]any{
			isin: map[string]any{
				"has_default":           false,
				"has_technical_default": false,
				"credit_rating":         rating,
			},
		},
		"bond_risk": map[string]any{
			isin: map[string]any{
				"has_default":           true,
				"has_technical_default": false,
			},
		},
	}
}

// BuildRiskDowngradeOverrides returns fake data that triggers a rating downgrade escalation.
func BuildRiskDowngradeOverrides(portfolioID, isin string) map[string]any {
	baseline := "ruBBB-"
	current := "ruBB+"
	return map[string]any{
		"portfolio_id": portfolioID,
		"put_offers":   map[string]any{},
		"risk_baselines": map[string]any{
			isin: map[string]any{
				"has_default":           false,
				"has_technical_default": false,
				"credit_rating":         baseline,
			},
		},
		"bond_risk": map[string]any{
			isin: map[string]any{
				"credit_rating": current,
			},
		},
	}
}

// LoadDevOverrides reads overrides for portfolioID. Returns nil if missing or mismatched.
func LoadDevOverrides(path, portfolioID string) *DevOverrides {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	var raw devOverridesFile
	if err := json.Unmarshal(data, &raw); err != nil {
		return nil
	}
	if raw.PortfolioID == "" || raw.PortfolioID != portfolioID {
		return nil
	}
	result := &DevOverrides{
		PortfolioID:   raw.PortfolioID,
		PutOffers:     raw.PutOffers,
		RiskBaselines: make(map[string]portfolio.RiskSnapshot, len(raw.RiskBaselines)),
		BondRisk:      raw.BondRisk,
	}
	for isin, entry := range raw.RiskBaselines {
		result.RiskBaselines[isin] = riskSnapshotFromJSON(entry)
	}
	if result.PutOffers == nil {
		result.PutOffers = map[string]devPutOfferOverride{}
	}
	if result.BondRisk == nil {
		result.BondRisk = map[string]map[string]any{}
	}
	return result
}

// SaveDevOverrides atomically writes overrides JSON.
func SaveDevOverrides(path string, payload map[string]any) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	data, err := json.MarshalIndent(payload, "", "  ")
	if err != nil {
		return err
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// ApplyDevNotificationOverrides patches universe, portfolio baselines, and positions in memory.
// Returns true when overrides were applied for portfolioID.
func ApplyDevNotificationOverrides(
	p *portfolio.Portfolio,
	universe []bonds.BondRecord,
	positions []portfolio.PortfolioPosition,
	portfolioID, path string,
	today time.Time,
) bool {
	overrides := LoadDevOverrides(path, portfolioID)
	if overrides == nil {
		return false
	}
	refDate := shared.DateOnly(today)
	universeByISIN := make(map[string]*bonds.BondRecord, len(universe))
	for i := range universe {
		universeByISIN[universe[i].ISIN] = &universe[i]
	}

	for isin, patch := range overrides.BondRisk {
		if bond, ok := universeByISIN[isin]; ok {
			applyBondRiskPatch(bond, patch)
		}
	}
	for isin, baseline := range overrides.RiskBaselines {
		if p.RiskBaselines == nil {
			p.RiskBaselines = make(map[string]portfolio.RiskSnapshot)
		}
		p.RiskBaselines[isin] = baseline
	}
	for isin, schedule := range overrides.PutOffers {
		bond, ok := universeByISIN[isin]
		if !ok {
			continue
		}
		applyPutOfferPatch(bond, schedule, refDate)
		for i := range positions {
			if positions[i].ISIN == isin {
				portfolio.SyncPutOfferFromBond(&positions[i], *bond)
			}
		}
	}
	return true
}

func riskSnapshotFromJSON(entry riskSnapshotJSON) portfolio.RiskSnapshot {
	return portfolio.RiskSnapshot{
		HasDefault:          entry.HasDefault,
		HasTechnicalDefault: entry.HasTechnicalDefault,
		CreditRating:        entry.CreditRating,
	}
}

func applyBondRiskPatch(bond *bonds.BondRecord, patch map[string]any) {
	if v, ok := patch["credit_rating"]; ok {
		if v == nil {
			bond.CreditRating = nil
		} else if s, ok := v.(string); ok {
			bond.CreditRating = &s
		}
	}
	if v, ok := patch["has_default"]; ok {
		if b, ok := v.(bool); ok {
			bond.HasDefault = b
		}
	}
	if v, ok := patch["has_technical_default"]; ok {
		if b, ok := v.(bool); ok {
			bond.HasTechnicalDefault = b
		}
	}
}

func applyPutOfferPatch(bond *bonds.BondRecord, schedule devPutOfferOverride, refDate time.Time) {
	offerDate := parseDate(schedule.OfferDate)
	submissionStart := parseDate(schedule.SubmissionStart)
	submissionEnd := parseDate(schedule.SubmissionEnd)
	if offerDate == nil || submissionStart == nil || submissionEnd == nil {
		return
	}
	bond.OfferDate = offerDate
	bond.OfferSubmissionStart = submissionStart
	bond.OfferSubmissionEnd = submissionEnd
	price := schedule.OfferPricePct
	if price == 0 {
		price = 100
	}
	bond.OfferPricePct = &price

	var dates []time.Time
	if bond.MaturityDate != nil && !bond.MaturityDate.Before(refDate) {
		dates = append(dates, *bond.MaturityDate)
	}
	if !offerDate.Before(refDate) {
		dates = append(dates, *offerDate)
	}
	if len(dates) > 0 {
		effective := dates[0]
		for _, d := range dates[1:] {
			if d.Before(effective) {
				effective = d
			}
		}
		bond.EffectiveDate = &effective
		days := shared.DaysBetween(refDate, effective)
		bond.DaysToMaturity = &days
	}
}

func parseDate(value string) *time.Time {
	if value == "" {
		return nil
	}
	t, err := time.Parse("2006-01-02", value)
	if err != nil {
		return nil
	}
	d := shared.DateOnly(t)
	return &d
}
