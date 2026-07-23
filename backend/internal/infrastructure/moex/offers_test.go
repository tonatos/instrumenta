package moex

import (
	"testing"
	"time"

	"github.com/tonatos/instrumenta/backend/internal/domain/bonds"
)

func TestOfferWindowFromMOEXRow(t *testing.T) {
	row := map[string]any{
		"isin":           "RU000A10AS28",
		"offerdate":      "2026-08-05",
		"offerdatestart": "2026-07-27",
		"offerdateend":   "2026-07-31",
		"price":          100.0,
	}
	got := offerWindowFromMOEXRow(row)
	if got.OfferDate == nil || got.OfferDate.Format("2006-01-02") != "2026-08-05" {
		t.Fatalf("offer date = %v", got.OfferDate)
	}
	if got.SubmissionStart == nil || got.SubmissionStart.Format("2006-01-02") != "2026-07-27" {
		t.Fatalf("start = %v", got.SubmissionStart)
	}
	if got.SubmissionEnd == nil || got.SubmissionEnd.Format("2006-01-02") != "2026-07-31" {
		t.Fatalf("end = %v", got.SubmissionEnd)
	}
	if got.PricePct == nil || *got.PricePct != 100 {
		t.Fatalf("price = %v", got.PricePct)
	}
}

func TestBuildBondRecord_AppliesMOEXOfferWindow(t *testing.T) {
	today := time.Date(2026, 7, 20, 0, 0, 0, 0, time.UTC)
	raw := map[string]any{
		"SECID": "RU000A10AS28", "SHORTNAME": "Test", "FACEUNIT": "SUR",
		"MATDATE": "2028-01-01", "OFFERDATE": "2026-08-05",
		"FACEVALUE": 1000.0, "LOTSIZE": 1.0, "LAST": 100.0, "YIELD": 15.0,
	}
	start := time.Date(2026, 7, 27, 0, 0, 0, 0, time.UTC)
	end := time.Date(2026, 7, 31, 0, 0, 0, 0, time.UTC)
	od := time.Date(2026, 8, 5, 0, 0, 0, 0, time.UTC)
	price := 100.0
	offers := []bonds.OfferWindowData{{
		OfferDate: &od, SubmissionStart: &start, SubmissionEnd: &end, PricePct: &price,
	}}
	bond := buildBondRecord("RU000A10AS28", raw, today, nil, offers)
	if bond == nil {
		t.Fatal("bond is nil")
	}
	if bond.OfferSubmissionStart == nil || !bond.OfferSubmissionStart.Equal(start) {
		t.Fatalf("start = %v", bond.OfferSubmissionStart)
	}
	if bond.OfferSubmissionEnd == nil || !bond.OfferSubmissionEnd.Equal(end) {
		t.Fatalf("end = %v", bond.OfferSubmissionEnd)
	}
	if bond.OfferPricePct == nil || *bond.OfferPricePct != 100 {
		t.Fatalf("price = %v", bond.OfferPricePct)
	}
}

func TestBuildBondRecord_SamoletPriceWithoutWindow(t *testing.T) {
	today := time.Date(2026, 7, 20, 0, 0, 0, 0, time.UTC)
	raw := map[string]any{
		"SECID": "RU000A109874", "SHORTNAME": "СамолетP15", "FACEUNIT": "SUR",
		"MATDATE": "2027-07-30", "OFFERDATE": "2026-08-07",
		"FACEVALUE": 1000.0, "LOTSIZE": 1.0, "LAST": 98.0, "YIELD": 20.0,
	}
	od := time.Date(2026, 8, 7, 0, 0, 0, 0, time.UTC)
	price := 100.0
	offers := []bonds.OfferWindowData{{OfferDate: &od, PricePct: &price}}
	bond := buildBondRecord("RU000A109874", raw, today, nil, offers)
	if bond == nil {
		t.Fatal("bond is nil")
	}
	if bond.OfferPricePct == nil || *bond.OfferPricePct != 100 {
		t.Fatalf("price = %v", bond.OfferPricePct)
	}
	if bond.OfferSubmissionStart != nil || bond.OfferSubmissionEnd != nil {
		t.Fatal("MOEX has no window yet — dates should stay nil for T-Invest fallback")
	}
}
