package portfolio_test

import (
	"testing"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
)

func TestDetectRiskEscalationDefault(t *testing.T) {
	baseline := portfolio.RiskSnapshot{}
	current := portfolio.RiskSnapshot{HasDefault: true}
	events := portfolio.DetectRiskEscalations(baseline, current, portfolio.DefaultRiskMonitorPolicy)
	if len(events) != 1 || events[0].Kind != portfolio.EscalationDefault {
		t.Fatalf("unexpected events: %+v", events)
	}
}

func TestRiskSnapshotFromBond(t *testing.T) {
	rating := "ruA"
	b := bonds.BondRecord{HasDefault: true, CreditRating: &rating}
	snap := portfolio.RiskSnapshotFromBond(b)
	if !snap.HasDefault || snap.CreditRating == nil || *snap.CreditRating != "ruA" {
		t.Fatalf("unexpected snapshot: %+v", snap)
	}
}
