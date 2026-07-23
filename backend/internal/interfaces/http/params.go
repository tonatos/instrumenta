package httpapi

import (
	"strings"

	"github.com/tonatos/instrumenta/backend/internal/domain/portfolio"
)

func ParseRiskProfile(value string) portfolio.RiskProfile {
	switch strings.ToLower(strings.TrimSpace(value)) {
	case string(portfolio.RiskProfileConservative):
		return portfolio.RiskProfileConservative
	case string(portfolio.RiskProfileAggressive):
		return portfolio.RiskProfileAggressive
	default:
		return portfolio.RiskProfileNormal
	}
}

func ParseRateScenario(value string) portfolio.RateScenario {
	switch strings.ToLower(strings.TrimSpace(value)) {
	case string(portfolio.RateScenarioCut):
		return portfolio.RateScenarioCut
	case string(portfolio.RateScenarioHike):
		return portfolio.RateScenarioHike
	default:
		return portfolio.RateScenarioHold
	}
}

func ResolveDurationPolicy(rateScenario string) portfolio.DurationPolicy {
	return portfolio.ResolveDurationPolicy(ParseRateScenario(rateScenario), nil, nil)
}

func DurationPolicyForPortfolio(p portfolio.Portfolio, rateScenario string) portfolio.DurationPolicy {
	return portfolio.DurationPolicyForPortfolio(p, ParseRateScenario(rateScenario))
}
