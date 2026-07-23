package trading

import (
	"context"
	"fmt"

	domainPortfolio "github.com/tonatos/instrumenta/backend/internal/domain/portfolio"
	"github.com/tonatos/instrumenta/backend/internal/domain/shared"
	"github.com/tonatos/instrumenta/backend/internal/domain/trading"
	"github.com/tonatos/instrumenta/backend/internal/interfaces/auth"
)

// SandboxUseCase manages sandbox accounts.
type SandboxUseCase struct {
	ctx    *Context
	broker *BrokerFacade
}

func NewSandboxUseCase(ctx *Context, broker *BrokerFacade) *SandboxUseCase {
	return &SandboxUseCase{ctx: ctx, broker: broker}
}

func (u *SandboxUseCase) ListAccounts(ctx context.Context, kind trading.AccountKind) ([]map[string]any, error) {
	accounts, err := u.broker.ListAccounts(ctx, kind)
	if err != nil {
		return nil, err
	}
	owner, ok := auth.OwnerTelegramID(ctx)
	var all []domainPortfolio.Portfolio
	var listErr error
	if ok {
		all, listErr = u.ctx.Repo().ListByOwner(ctx, owner)
	} else {
		all, listErr = u.ctx.Repo().ListAll(ctx)
	}
	if listErr != nil {
		return nil, listErr
	}
	linked := map[string]domainPortfolio.Portfolio{}
	for _, p := range all {
		if p.Mode == domainPortfolio.PortfolioModeTrading && p.AccountID != nil && p.AccountKind != nil && *p.AccountKind == kind {
			linked[*p.AccountID] = p
		}
	}
	result := make([]map[string]any, 0, len(accounts))
	for _, account := range accounts {
		item := map[string]any{
			"id": account.ID, "name": account.Name, "kind": string(kind),
			"is_writable": account.IsWritable,
		}
		if lp, ok := linked[account.ID]; ok {
			item["linked_portfolio"] = map[string]string{"id": lp.ID, "name": lp.Name}
		}
		result = append(result, item)
	}
	return result, nil
}

func (u *SandboxUseCase) CreateSandboxAccount(ctx context.Context, initialAmountRub float64, name string) (map[string]any, error) {
	if initialAmountRub <= 0 {
		return nil, fmt.Errorf("amount must be positive")
	}
	accountName := name
	if accountName == "" {
		accountName = "instrumenta"
	}
	accountID, err := u.broker.OpenSandboxAccount(ctx, accountName)
	if err != nil {
		return nil, err
	}
	balance, err := u.broker.SandboxPayIn(ctx, accountID, shared.Rub(initialAmountRub))
	if err != nil {
		return nil, err
	}
	return map[string]any{
		"id": accountID, "name": accountName, "kind": string(trading.AccountKindSandbox),
		"money_rub": float64(balance),
	}, nil
}

func (u *SandboxUseCase) DeleteSandboxAccount(ctx context.Context, accountID string) (map[string]any, error) {
	kind := trading.AccountKindSandbox
	linked, _ := u.ctx.FindLinkedPortfolio(ctx, accountID, kind, "")
	var deletedPortfolioID *string
	if linked != nil {
		deletedPortfolioID = &linked.ID
		if _, err := u.ctx.Repo().Delete(ctx, linked.ID); err != nil {
			return nil, err
		}
	}
	if err := u.broker.CloseSandboxAccount(ctx, accountID); err != nil {
		return nil, err
	}
	result := map[string]any{"account_id": accountID}
	if deletedPortfolioID != nil {
		result["deleted_portfolio_id"] = *deletedPortfolioID
	}
	return result, nil
}

func (u *SandboxUseCase) SandboxPayInForPortfolio(ctx context.Context, portfolioID string, amountRub float64) (map[string]any, error) {
	p, err := u.ctx.GetTradingPortfolio(ctx, portfolioID)
	if err != nil {
		return nil, mapTradingErr(err)
	}
	if p.AccountKind == nil || *p.AccountKind != trading.AccountKindSandbox {
		return nil, fmt.Errorf("Пополнение доступно только для песочницы")
	}
	if amountRub <= 0 {
		return nil, fmt.Errorf("Сумма пополнения должна быть больше нуля")
	}
	balance, err := u.broker.SandboxPayIn(ctx, *p.AccountID, shared.Rub(amountRub))
	if err != nil {
		return nil, err
	}
	return map[string]any{
		"amount_added_rub": amountRub,
		"money_rub":        float64(balance),
	}, nil
}
