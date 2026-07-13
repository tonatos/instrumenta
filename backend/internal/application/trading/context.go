package trading

import (
	"context"
	"fmt"
	"time"

	domainPortfolio "github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
	"github.com/tonatos/bond-monitor/backend/internal/domain/shared"
	"github.com/tonatos/bond-monitor/backend/internal/domain/trading"
)

// Context provides repository access and token resolution for trading use cases.
type Context struct {
	repo             domainPortfolio.Repository
	sandboxToken     string
	productionToken  string
}

func NewContext(repo domainPortfolio.Repository, sandboxToken, productionToken string) *Context {
	return &Context{repo: repo, sandboxToken: sandboxToken, productionToken: productionToken}
}

func (c *Context) Repo() domainPortfolio.Repository { return c.repo }

func (c *Context) Token(kind trading.AccountKind) (string, error) {
	token := c.productionToken
	if kind == trading.AccountKindSandbox {
		token = c.sandboxToken
	}
	if token == "" {
		return "", fmt.Errorf("trading token for %s not configured", kind)
	}
	return token, nil
}

func (c *Context) GetTradingPortfolio(ctx context.Context, portfolioID string) (domainPortfolio.Portfolio, error) {
	p, err := c.repo.GetByID(ctx, portfolioID)
	if err != nil {
		return domainPortfolio.Portfolio{}, err
	}
	if p == nil {
		return domainPortfolio.Portfolio{}, fmt.Errorf("portfolio not found")
	}
	if !p.IsTrading() || p.AccountID == nil || p.AccountKind == nil {
		return domainPortfolio.Portfolio{}, fmt.Errorf("portfolio is not in trading mode")
	}
	return *p, nil
}

func (c *Context) FindLinkedPortfolio(ctx context.Context, accountID string, kind trading.AccountKind, excludePortfolioID string) (*domainPortfolio.Portfolio, error) {
	all, err := c.repo.ListAll(ctx)
	if err != nil {
		return nil, err
	}
	for _, p := range all {
		if p.Mode != domainPortfolio.PortfolioModeTrading {
			continue
		}
		if p.AccountID == nil || *p.AccountID != accountID {
			continue
		}
		if p.AccountKind == nil || *p.AccountKind != kind {
			continue
		}
		if excludePortfolioID != "" && p.ID == excludePortfolioID {
			continue
		}
		return &p, nil
	}
	return nil, nil
}

// BrokerFacade resolves tokens and delegates to trading.BrokerClient.
type BrokerFacade struct {
	sandbox    trading.BrokerClient
	production trading.BrokerClient
}

func NewBrokerFacade(sandbox, production trading.BrokerClient) *BrokerFacade {
	return &BrokerFacade{sandbox: sandbox, production: production}
}

func (b *BrokerFacade) client(kind trading.AccountKind) trading.BrokerClient {
	if kind == trading.AccountKindSandbox {
		return b.sandbox
	}
	return b.production
}

func (b *BrokerFacade) GetAccountSnapshot(kind trading.AccountKind, accountID string) (trading.InfraAccountSnapshot, error) {
	return b.client(kind).GetAccountSnapshot(kind, accountID)
}

func (b *BrokerFacade) GetAccountOperations(kind trading.AccountKind, accountID string, fromDate time.Time) ([]trading.InfraOperationRecord, error) {
	return b.client(kind).GetAccountOperations(kind, accountID, fromDate)
}

func (b *BrokerFacade) GetActiveOrders(kind trading.AccountKind, accountID string) ([]trading.InfraOrderState, error) {
	return b.client(kind).GetActiveOrders(kind, accountID)
}

func (b *BrokerFacade) ListAccounts(kind trading.AccountKind) ([]trading.AccountInfo, error) {
	return b.client(kind).ListAccounts(kind)
}

func (b *BrokerFacade) ResolveFIGIForISIN(kind trading.AccountKind, isin string) (string, error) {
	return b.client(kind).ResolveFIGIForISIN(isin)
}

func (b *BrokerFacade) EnsureOrderInstrument(kind trading.AccountKind, figi, instrumentUID, isin string, direction trading.OrderDirection) (trading.TradeInstrument, error) {
	return b.client(kind).EnsureOrderInstrument(figi, instrumentUID, isin, direction)
}

func (b *BrokerFacade) PreviewOrderPrice(kind trading.AccountKind, accountID, figi, instrumentUID string, direction trading.OrderDirection, lots shared.Lots, pricePct shared.PriceUnitPct) (trading.InfraOrderPricePreview, error) {
	return b.client(kind).PreviewOrderPrice(kind, accountID, figi, instrumentUID, direction, lots, pricePct)
}

func (b *BrokerFacade) PostLimitOrder(kind trading.AccountKind, accountID, figi, instrumentUID string, direction trading.OrderDirection, lots shared.Lots, pricePct shared.PriceUnitPct, requestUID string) (trading.InfraPostOrderResult, error) {
	return b.client(kind).PostLimitOrder(kind, accountID, figi, instrumentUID, direction, lots, pricePct, requestUID)
}

func (b *BrokerFacade) PostMarketSellOrder(kind trading.AccountKind, accountID, figi, instrumentUID string, lots shared.Lots, requestUID string, referencePricePct *shared.PriceUnitPct, lotSize int) (trading.InfraPostOrderResult, error) {
	return b.client(kind).PostMarketSellOrder(kind, accountID, figi, instrumentUID, lots, requestUID, referencePricePct, lotSize)
}

func (b *BrokerFacade) CancelOrder(kind trading.AccountKind, accountID, orderID string) error {
	return b.client(kind).CancelOrder(kind, accountID, orderID)
}

func (b *BrokerFacade) OpenSandboxAccount(name string) (string, error) {
	return b.sandbox.OpenSandboxAccount(name)
}

func (b *BrokerFacade) CloseSandboxAccount(accountID string) error {
	return b.sandbox.CloseSandboxAccount(accountID)
}

func (b *BrokerFacade) SandboxPayIn(accountID string, amount shared.Rub) (shared.Rub, error) {
	return b.sandbox.SandboxPayIn(accountID, amount)
}

func (b *BrokerFacade) MakeRequestUID(kind trading.AccountKind, accountID, figi, direction string, lots int, orderKey, salt string) string {
	return b.client(kind).MakeRequestUID(accountID, figi, direction, lots, orderKey, salt)
}

func (b *BrokerFacade) CheckTradeAvailable(kind trading.AccountKind, figi, instrumentUID string) (*trading.TradeInstrument, error) {
	return b.client(kind).CheckTradeAvailable(figi, instrumentUID)
}

func (b *BrokerFacade) GetLastPricePct(kind trading.AccountKind, figi string) (*float64, error) {
	return b.client(kind).GetLastPricePct(figi)
}
