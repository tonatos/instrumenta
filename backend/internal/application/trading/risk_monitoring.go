package trading

import (
	"context"
	"fmt"

	"github.com/tonatos/instrumenta/backend/internal/domain/bonds"
	domainPortfolio "github.com/tonatos/instrumenta/backend/internal/domain/portfolio"
)

// PrepareTradingRiskMonitoring syncs risk baselines for holdings at attach time.
func PrepareTradingRiskMonitoring(ctx context.Context, tradingCtx *Context, p *domainPortfolio.Portfolio, universe []bonds.BondRecord, holdingISINs map[string]struct{}) error {
	universeByISIN := make(map[string]bonds.BondRecord, len(universe))
	for _, bond := range universe {
		universeByISIN[bond.ISIN] = bond
	}
	changed := domainPortfolio.SyncRiskBaselines(p.RiskBaselines, holdingISINs, universeByISIN)
	if changed {
		p.Touch()
		_, err := tradingCtx.Repo().Save(ctx, *p)
		return err
	}
	return nil
}

// AcknowledgeTradingRisk accepts current risk state as baseline for a held ISIN.
func AcknowledgeTradingRisk(ctx context.Context, tradingCtx *Context, portfolioID, isin string, universe []bonds.BondRecord) error {
	p, err := tradingCtx.GetTradingPortfolio(ctx, portfolioID)
	if err != nil {
		return mapTradingErr(err)
	}
	var bond *bonds.BondRecord
	for i := range universe {
		if universe[i].ISIN == isin {
			bond = &universe[i]
			break
		}
	}
	if bond == nil {
		return fmt.Errorf("Bond %s not found in market universe", isin)
	}
	domainPortfolio.AcknowledgeRiskBaseline(p.RiskBaselines, isin, *bond)
	p.Touch()
	_, err = tradingCtx.Repo().Save(ctx, p)
	return err
}
