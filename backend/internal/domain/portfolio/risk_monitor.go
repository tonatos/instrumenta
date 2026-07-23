package portfolio

import (
	"fmt"

	"github.com/tonatos/instrumenta/backend/internal/domain/bonds"
)

type RiskUrgency string

const (
	RiskUrgencySoon     RiskUrgency = "soon"
	RiskUrgencyCritical RiskUrgency = "critical"
)

type EscalationKind string

const (
	EscalationDefault           EscalationKind = "default"
	EscalationTechnicalDefault  EscalationKind = "technical_default"
	EscalationDistressRating    EscalationKind = "distress_rating"
	EscalationIGExit            EscalationKind = "ig_exit"
	EscalationMajorDowngrade    EscalationKind = "major_downgrade"
)

type RiskEscalation struct {
	Kind     EscalationKind
	Urgency  RiskUrgency
	Reason   string
}

func RiskSnapshotFromBond(b bonds.BondRecord) RiskSnapshot {
	return RiskSnapshot{
		HasDefault: b.HasDefault, HasTechnicalDefault: b.HasTechnicalDefault,
		CreditRating: b.CreditRating,
	}
}

func ratingOrdinalValue(rating *string) *int {
	if rating == nil {
		return nil
	}
	if ord, ok := bonds.RatingOrder[*rating]; ok {
		return &ord
	}
	return nil
}

func DetectRiskEscalations(baseline, current RiskSnapshot, policy RiskMonitorPolicy) []RiskEscalation {
	var events []RiskEscalation
	if !baseline.HasDefault && current.HasDefault {
		events = append(events, RiskEscalation{
			Kind: EscalationDefault, Urgency: RiskUrgencyCritical,
			Reason: "Эмитент в дефолте по данным MOEX",
		})
	}
	if !baseline.HasTechnicalDefault && current.HasTechnicalDefault {
		events = append(events, RiskEscalation{
			Kind: EscalationTechnicalDefault, Urgency: RiskUrgencyCritical,
			Reason: "Технический дефолт по данным MOEX",
		})
	}
	baseOrd := ratingOrdinalValue(baseline.CreditRating)
	currOrd := ratingOrdinalValue(current.CreditRating)
	if baseOrd != nil && currOrd != nil && *currOrd < *baseOrd {
		var ratingEvent *RiskEscalation
		if *currOrd <= policy.DistressRatingOrdinalMax {
			ratingEvent = &RiskEscalation{
				Kind: EscalationDistressRating, Urgency: RiskUrgencyCritical,
				Reason: fmt.Sprintf("Кредитный рейтинг снизился до %s (было %s)", derefStr(current.CreditRating), derefStr(baseline.CreditRating)),
			}
		} else if *baseOrd >= policy.InvestmentGradeOrdinalMin && *currOrd < policy.InvestmentGradeOrdinalMin {
			ratingEvent = &RiskEscalation{
				Kind: EscalationIGExit, Urgency: RiskUrgencySoon,
				Reason: fmt.Sprintf("Рейтинг вышел из investment grade: %s → %s", derefStr(baseline.CreditRating), derefStr(current.CreditRating)),
			}
		} else if *baseOrd-*currOrd >= policy.MajorDowngradeSteps {
			ratingEvent = &RiskEscalation{
				Kind: EscalationMajorDowngrade, Urgency: RiskUrgencySoon,
				Reason: fmt.Sprintf("Кредитный рейтинг существенно снижен: %s → %s", derefStr(baseline.CreditRating), derefStr(current.CreditRating)),
			}
		}
		if ratingEvent != nil {
			events = append(events, *ratingEvent)
		}
	}
	return events
}

func derefStr(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

func SyncRiskBaselines(baselines map[string]RiskSnapshot, holdingISINs map[string]struct{}, universeByISIN map[string]bonds.BondRecord) bool {
	changed := false
	for isin := range baselines {
		if _, ok := holdingISINs[isin]; !ok {
			delete(baselines, isin)
			changed = true
		}
	}
	for isin := range holdingISINs {
		if _, ok := baselines[isin]; ok {
			continue
		}
		if bond, ok := universeByISIN[isin]; ok {
			baselines[isin] = RiskSnapshotFromBond(bond)
			changed = true
		}
	}
	return changed
}

func AcknowledgeRiskBaseline(baselines map[string]RiskSnapshot, isin string, bond bonds.BondRecord) {
	baselines[isin] = RiskSnapshotFromBond(bond)
}
