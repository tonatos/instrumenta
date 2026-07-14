package trading

import (
	"testing"
	"time"

	domainNotifications "github.com/tonatos/bond-monitor/backend/internal/domain/notifications"
	domainTrading "github.com/tonatos/bond-monitor/backend/internal/domain/trading"
)

func TestTurboEntrySuggestionsFromNotifications(t *testing.T) {
	now := time.Date(2026, 7, 28, 0, 0, 0, 0, time.UTC)
	recs := []domainNotifications.NotificationRecord{
		{
			ID: "n1", PortfolioID: "p1", Kind: "turbo_entry", Urgency: "normal",
			CreatedAt: now,
			Payload: map[string]any{
				"isin":               "RU000TURBO1",
				"name":               "Turbo Bond",
				"reason":             "Turbo-entry reason",
				"suggested_price_pct": 99.1,
				"market_price_pct":    100.0,
				"lots":               2.0,
				"figi":               "FIGI_TURBO",
			},
		},
	}
	s := turboEntrySuggestionsFromNotifications("p1", recs)
	if len(s) != 1 {
		t.Fatalf("expected 1 suggestion, got %d", len(s))
	}
	if s[0].Kind != domainTrading.SuggestionKindBuy {
		t.Fatalf("expected buy kind, got %s", s[0].Kind)
	}
	if s[0].ISIN != "RU000TURBO1" || s[0].Name != "Turbo Bond" {
		t.Fatalf("unexpected isin/name: %+v", s[0])
	}
	if s[0].Lots != 2 {
		t.Fatalf("expected lots 2, got %d", s[0].Lots)
	}
	if s[0].FIGI == nil || *s[0].FIGI != "FIGI_TURBO" {
		t.Fatalf("unexpected figi: %+v", s[0].FIGI)
	}
	if s[0].SuggestedPricePct == nil || *s[0].SuggestedPricePct != 99.1 {
		t.Fatalf("unexpected suggested price: %+v", s[0].SuggestedPricePct)
	}
}

