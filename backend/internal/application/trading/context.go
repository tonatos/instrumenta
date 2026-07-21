package trading

import (
	"context"
	"errors"
	"fmt"
	"time"

	domainPortfolio "github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
	"github.com/tonatos/bond-monitor/backend/internal/domain/shared"
	"github.com/tonatos/bond-monitor/backend/internal/domain/trading"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/persistence"
	"github.com/tonatos/bond-monitor/backend/internal/interfaces/auth"
)

// ErrBrokerCredentialsRequired is returned when the owner has no token for the account kind.
var ErrBrokerCredentialsRequired = errors.New("broker_credentials_required")

// TokenSource resolves plaintext broker tokens for a tenant.
type TokenSource interface {
	TokenFor(ctx context.Context, ownerTelegramID int64, kind trading.AccountKind) (string, error)
}

// CredentialTokenSource reads encrypted credentials with optional env fallback (AUTH_DISABLED only).
type CredentialTokenSource struct {
	Repo               *persistence.BrokerCredentialsRepository
	SandboxEnvToken    string
	ProductionEnvToken string
	AllowEnvFallback   bool
}

func (s *CredentialTokenSource) TokenFor(ctx context.Context, ownerTelegramID int64, kind trading.AccountKind) (string, error) {
	if s.Repo != nil {
		token, err := s.Repo.GetPlaintext(ctx, ownerTelegramID, kind)
		if err == nil && token != "" {
			return token, nil
		}
		if err != nil && !errors.Is(err, persistence.ErrBrokerCredentialMissing) {
			return "", err
		}
	}
	if s.AllowEnvFallback {
		token := s.ProductionEnvToken
		if kind == trading.AccountKindSandbox {
			token = s.SandboxEnvToken
		}
		if token != "" {
			return token, nil
		}
	}
	return "", ErrBrokerCredentialsRequired
}

// Context provides repository access and token resolution for trading use cases.
type Context struct {
	repo   domainPortfolio.Repository
	tokens TokenSource
}

func NewContext(repo domainPortfolio.Repository, tokens TokenSource) *Context {
	return &Context{repo: repo, tokens: tokens}
}

func (c *Context) Repo() domainPortfolio.Repository { return c.repo }

func (c *Context) TokenFor(ctx context.Context, ownerTelegramID int64, kind trading.AccountKind) (string, error) {
	if c.tokens == nil {
		return "", ErrBrokerCredentialsRequired
	}
	return c.tokens.TokenFor(ctx, ownerTelegramID, kind)
}

// Token resolves a token for the owner attached to ctx.
func (c *Context) Token(ctx context.Context, kind trading.AccountKind) (string, error) {
	owner, ok := auth.OwnerTelegramID(ctx)
	if !ok {
		return "", ErrBrokerCredentialsRequired
	}
	return c.TokenFor(ctx, owner, kind)
}

func (c *Context) GetTradingPortfolio(ctx context.Context, portfolioID string) (domainPortfolio.Portfolio, error) {
	p, err := c.GetOwnedPortfolio(ctx, portfolioID)
	if err != nil {
		return domainPortfolio.Portfolio{}, err
	}
	if !p.IsTrading() || p.AccountID == nil || p.AccountKind == nil {
		return domainPortfolio.Portfolio{}, fmt.Errorf("portfolio is not in trading mode")
	}
	return p, nil
}

func (c *Context) GetOwnedPortfolio(ctx context.Context, portfolioID string) (domainPortfolio.Portfolio, error) {
	owner, ok := auth.OwnerTelegramID(ctx)
	if !ok {
		return domainPortfolio.Portfolio{}, fmt.Errorf("portfolio not found")
	}
	p, err := c.repo.GetByIDForOwner(ctx, portfolioID, owner)
	if err != nil {
		return domainPortfolio.Portfolio{}, err
	}
	if p == nil {
		return domainPortfolio.Portfolio{}, fmt.Errorf("portfolio not found")
	}
	return *p, nil
}

func (c *Context) FindLinkedPortfolio(ctx context.Context, accountID string, kind trading.AccountKind, excludePortfolioID string) (*domainPortfolio.Portfolio, error) {
	owner, ok := auth.OwnerTelegramID(ctx)
	var all []domainPortfolio.Portfolio
	var err error
	if ok {
		all, err = c.repo.ListByOwner(ctx, owner)
	} else {
		all, err = c.repo.ListAll(ctx)
	}
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

// BrokerFacade resolves tokens per call using owner from ctx and delegates to BrokerClient.
type BrokerFacade struct {
	tokens TokenSource
}

func NewBrokerFacade(tokens TokenSource) *BrokerFacade {
	return &BrokerFacade{tokens: tokens}
}

func (b *BrokerFacade) client(ctx context.Context, kind trading.AccountKind) (trading.BrokerClient, error) {
	owner, ok := auth.OwnerTelegramID(ctx)
	if !ok {
		return nil, ErrBrokerCredentialsRequired
	}
	if b.tokens == nil {
		return nil, ErrBrokerCredentialsRequired
	}
	token, err := b.tokens.TokenFor(ctx, owner, kind)
	if err != nil {
		return nil, err
	}
	client := newBrokerClient(token, kind)
	if client == nil {
		return nil, ErrBrokerCredentialsRequired
	}
	return client, nil
}

func (b *BrokerFacade) GetAccountSnapshot(ctx context.Context, kind trading.AccountKind, accountID string) (trading.InfraAccountSnapshot, error) {
	client, err := b.client(ctx, kind)
	if err != nil {
		return trading.InfraAccountSnapshot{}, err
	}
	return client.GetAccountSnapshot(kind, accountID)
}

func (b *BrokerFacade) GetAccountOperations(ctx context.Context, kind trading.AccountKind, accountID string, fromDate time.Time) ([]trading.InfraOperationRecord, error) {
	client, err := b.client(ctx, kind)
	if err != nil {
		return nil, err
	}
	return client.GetAccountOperations(kind, accountID, fromDate)
}

func (b *BrokerFacade) GetActiveOrders(ctx context.Context, kind trading.AccountKind, accountID string) ([]trading.InfraOrderState, error) {
	client, err := b.client(ctx, kind)
	if err != nil {
		return nil, err
	}
	return client.GetActiveOrders(kind, accountID)
}

func (b *BrokerFacade) ListAccounts(ctx context.Context, kind trading.AccountKind) ([]trading.AccountInfo, error) {
	client, err := b.client(ctx, kind)
	if err != nil {
		return nil, err
	}
	return client.ListAccounts(kind)
}

func (b *BrokerFacade) ResolveFIGIForISIN(ctx context.Context, kind trading.AccountKind, isin string) (string, error) {
	client, err := b.client(ctx, kind)
	if err != nil {
		return "", err
	}
	return client.ResolveFIGIForISIN(isin)
}

func (b *BrokerFacade) EnsureOrderInstrument(ctx context.Context, kind trading.AccountKind, figi, instrumentUID, isin string, direction trading.OrderDirection) (trading.TradeInstrument, error) {
	client, err := b.client(ctx, kind)
	if err != nil {
		return trading.TradeInstrument{}, err
	}
	return client.EnsureOrderInstrument(figi, instrumentUID, isin, direction)
}

func (b *BrokerFacade) PreviewOrderPrice(ctx context.Context, kind trading.AccountKind, accountID, figi, instrumentUID string, direction trading.OrderDirection, lots shared.Lots, pricePct shared.PriceUnitPct) (trading.InfraOrderPricePreview, error) {
	client, err := b.client(ctx, kind)
	if err != nil {
		return trading.InfraOrderPricePreview{}, err
	}
	return client.PreviewOrderPrice(kind, accountID, figi, instrumentUID, direction, lots, pricePct)
}

func (b *BrokerFacade) PostLimitOrder(ctx context.Context, kind trading.AccountKind, accountID, figi, instrumentUID string, direction trading.OrderDirection, lots shared.Lots, pricePct shared.PriceUnitPct, requestUID string) (trading.InfraPostOrderResult, error) {
	client, err := b.client(ctx, kind)
	if err != nil {
		return trading.InfraPostOrderResult{}, err
	}
	return client.PostLimitOrder(kind, accountID, figi, instrumentUID, direction, lots, pricePct, requestUID)
}

func (b *BrokerFacade) PostMarketSellOrder(ctx context.Context, kind trading.AccountKind, accountID, figi, instrumentUID string, lots shared.Lots, requestUID string, referencePricePct *shared.PriceUnitPct, lotSize int) (trading.InfraPostOrderResult, error) {
	client, err := b.client(ctx, kind)
	if err != nil {
		return trading.InfraPostOrderResult{}, err
	}
	return client.PostMarketSellOrder(kind, accountID, figi, instrumentUID, lots, requestUID, referencePricePct, lotSize)
}

func (b *BrokerFacade) CancelOrder(ctx context.Context, kind trading.AccountKind, accountID, orderID string) error {
	client, err := b.client(ctx, kind)
	if err != nil {
		return err
	}
	return client.CancelOrder(kind, accountID, orderID)
}

func (b *BrokerFacade) OpenSandboxAccount(ctx context.Context, name string) (string, error) {
	client, err := b.client(ctx, trading.AccountKindSandbox)
	if err != nil {
		return "", err
	}
	return client.OpenSandboxAccount(name)
}

func (b *BrokerFacade) CloseSandboxAccount(ctx context.Context, accountID string) error {
	client, err := b.client(ctx, trading.AccountKindSandbox)
	if err != nil {
		return err
	}
	return client.CloseSandboxAccount(accountID)
}

func (b *BrokerFacade) SandboxPayIn(ctx context.Context, accountID string, amount shared.Rub) (shared.Rub, error) {
	client, err := b.client(ctx, trading.AccountKindSandbox)
	if err != nil {
		return 0, err
	}
	return client.SandboxPayIn(accountID, amount)
}

func (b *BrokerFacade) MakeRequestUID(ctx context.Context, kind trading.AccountKind, accountID, figi, direction string, lots int, orderKey, salt string) string {
	client, err := b.client(ctx, kind)
	if err != nil {
		return ""
	}
	return client.MakeRequestUID(accountID, figi, direction, lots, orderKey, salt)
}

func (b *BrokerFacade) CheckTradeAvailable(ctx context.Context, kind trading.AccountKind, figi, instrumentUID string) (*trading.TradeInstrument, error) {
	client, err := b.client(ctx, kind)
	if err != nil {
		return nil, err
	}
	return client.CheckTradeAvailable(figi, instrumentUID)
}

func (b *BrokerFacade) GetLastPricePct(ctx context.Context, kind trading.AccountKind, figi string) (*float64, error) {
	client, err := b.client(ctx, kind)
	if err != nil {
		return nil, err
	}
	return client.GetLastPricePct(figi)
}
