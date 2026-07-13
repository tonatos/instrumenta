package trading

import (
	"context"
	"errors"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/application"
	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	domainPortfolio "github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
	"github.com/tonatos/bond-monitor/backend/internal/domain/trading"
)

// Service is the application facade for trading mode operations.
type Service struct {
	ctx            *Context
	sandbox        *SandboxUseCase
	attach         *AttachUseCase
	advise         *AdviseUseCase
	tradingState   *TradingStateUseCase
	deploySessions *DeploySessionUseCase
	orders         *OrderUseCase
	sell           *SellPositionUseCase
}

// NewService wires trading use cases behind application.TradingService.
func NewService(
	repo domainPortfolio.Repository,
	deployRepo trading.DeploySessionRepository,
	sandboxToken, productionToken string,
) *Service {
	ctx := NewContext(repo, sandboxToken, productionToken)
	sandboxClient := tradingClient(sandboxToken, trading.AccountKindSandbox)
	productionClient := tradingClient(productionToken, trading.AccountKindProduction)
	broker := NewBrokerFacade(sandboxClient, productionClient)
	policy := trading.DefaultDeploySessionPolicy()
	deploySessions := NewDeploySessionUseCase(ctx, deployRepo, broker, policy)
	advise := NewAdviseUseCase(ctx, deploySessions, broker)
	return &Service{
		ctx:            ctx,
		sandbox:        NewSandboxUseCase(ctx, broker),
		attach:         NewAttachUseCase(ctx, broker),
		advise:         advise,
		tradingState:   NewTradingStateUseCase(ctx, advise, broker),
		deploySessions: deploySessions,
		orders:         NewOrderUseCase(ctx, broker, deploySessions),
		sell:           NewSellPositionUseCase(ctx, broker),
	}
}

func tradingClient(token string, kind trading.AccountKind) trading.BrokerClient {
	if token == "" {
		return nil
	}
	// SDK client is wired in infrastructure/tinvest; import lazily via package function.
	return newBrokerClient(token, kind)
}

func (s *Service) ListAccounts(ctx context.Context, kind trading.AccountKind) ([]map[string]any, error) {
	return s.sandbox.ListAccounts(ctx, kind)
}

func (s *Service) CreateSandboxAccount(ctx context.Context, initialAmountRub float64, name *string) (map[string]any, error) {
	_ = ctx
	accountName := ""
	if name != nil {
		accountName = *name
	}
	return s.sandbox.CreateSandboxAccount(initialAmountRub, accountName)
}

func (s *Service) DeleteSandboxAccount(ctx context.Context, accountID string) (map[string]any, error) {
	return s.sandbox.DeleteSandboxAccount(ctx, accountID)
}

func (s *Service) GetAccountPreview(ctx context.Context, portfolioID, accountID string, kind trading.AccountKind, universe []bonds.BondRecord) (map[string]any, error) {
	preview, err := s.attach.GetAccountPreview(ctx, portfolioID, accountID, kind, universe)
	if err != nil {
		return nil, mapAttachErr(err)
	}
	return preview, nil
}

func (s *Service) ClearAccountForAttach(ctx context.Context, portfolioID, accountID string, kind trading.AccountKind, payInRub *float64, universe []bonds.BondRecord) (map[string]any, error) {
	preview, err := s.attach.ClearAccountForAttach(ctx, portfolioID, accountID, kind, payInRub, universe)
	if err != nil {
		return nil, mapAttachErr(err)
	}
	return preview, nil
}

func (s *Service) AttachAccount(ctx context.Context, portfolioID, accountID string, kind trading.AccountKind, universe []bonds.BondRecord, keyRate, taxRate float64, today time.Time) (domainPortfolio.Portfolio, error) {
	p, err := s.attach.AttachAccount(ctx, portfolioID, accountID, kind, universe, keyRate, taxRate, today)
	if err != nil {
		return domainPortfolio.Portfolio{}, mapAttachErr(err)
	}
	return p, nil
}

func (s *Service) DetachAccount(ctx context.Context, portfolioID string) (domainPortfolio.Portfolio, error) {
	p, err := s.attach.DetachAccount(ctx, portfolioID)
	if err != nil {
		return domainPortfolio.Portfolio{}, mapAttachErr(err)
	}
	return p, nil
}

func (s *Service) SandboxPayIn(ctx context.Context, portfolioID string, amountRub float64) (map[string]any, error) {
	return s.sandbox.SandboxPayInForPortfolio(ctx, portfolioID, amountRub)
}

func (s *Service) GetAdvice(ctx context.Context, portfolioID string, universe []bonds.BondRecord, keyRate, taxRate float64, today time.Time, durationPolicy domainPortfolio.DurationPolicy) (application.TradingAdviceResult, error) {
	return s.advise.GetAdvice(ctx, portfolioID, universe, keyRate, taxRate, today, &durationPolicy)
}

func (s *Service) GetTradingState(ctx context.Context, portfolioID string, universe []bonds.BondRecord, keyRate, taxRate float64, today time.Time, durationPolicy domainPortfolio.DurationPolicy) (application.TradingStateResult, error) {
	return s.tradingState.GetTradingState(ctx, portfolioID, universe, keyRate, taxRate, today, &durationPolicy)
}

func (s *Service) BuildTradingPlan(ctx context.Context, portfolioID string, universe []bonds.BondRecord, keyRate, taxRate float64, today time.Time, durationPolicy domainPortfolio.DurationPolicy) (domainPortfolio.PortfolioPlan, error) {
	p, err := s.ctx.GetTradingPortfolio(ctx, portfolioID)
	if err != nil {
		return domainPortfolio.PortfolioPlan{}, mapTradingErr(err)
	}
	kind := *p.AccountKind
	accountID := *p.AccountID
	snapshot, err := s.orders.broker.GetAccountSnapshot(kind, accountID)
	if err != nil {
		return domainPortfolio.PortfolioPlan{}, err
	}
	brokerSnapshot := toBrokerSnapshot(snapshot)
	return BuildTradingPlan(p, brokerSnapshot, universe, keyRate, taxRate, today, &durationPolicy), nil
}

func (s *Service) CreateDeploySession(ctx context.Context, portfolioID string, universe []bonds.BondRecord, keyRate, taxRate float64, today time.Time) (trading.DeploySession, error) {
	session, err := s.deploySessions.CreateSession(ctx, portfolioID, universe, keyRate, taxRate, today)
	return session, mapDeployErr(err)
}

func (s *Service) GetActiveDeploySession(ctx context.Context, portfolioID string) (*trading.DeploySession, error) {
	if _, err := s.ctx.GetTradingPortfolio(ctx, portfolioID); err != nil {
		return nil, mapTradingErr(err)
	}
	return s.deploySessions.GetActive(ctx, portfolioID)
}

func (s *Service) RefreshDeploySession(ctx context.Context, portfolioID, sessionID string, universe []bonds.BondRecord, keyRate, taxRate float64, today time.Time) (trading.DeploySession, error) {
	session, err := s.deploySessions.RefreshSession(ctx, portfolioID, sessionID, universe, keyRate, taxRate, today)
	return session, mapDeployErr(err)
}

func (s *Service) CancelDeploySession(ctx context.Context, portfolioID, sessionID string) (trading.DeploySession, error) {
	session, err := s.deploySessions.CancelSession(ctx, portfolioID, sessionID)
	return session, mapDeployErr(err)
}

func (s *Service) SkipDeploySessionItem(ctx context.Context, portfolioID, sessionID, itemID string) (trading.DeploySession, error) {
	session, err := s.deploySessions.SkipItem(ctx, portfolioID, sessionID, itemID)
	return session, mapDeployErr(err)
}

func (s *Service) AcknowledgeRiskAlert(ctx context.Context, portfolioID, isin string, universe []bonds.BondRecord) error {
	return mapTradingErr(AcknowledgeTradingRisk(ctx, s.ctx, portfolioID, isin, universe))
}

func (s *Service) PreviewOrder(ctx context.Context, portfolioID string, universe []bonds.BondRecord, isin, direction string, lots int, pricePct float64, figi *string) (map[string]any, error) {
	result, err := s.orders.PreviewOrder(ctx, portfolioID, universe, isin, trading.OrderDirection(direction), lots, pricePct, figi)
	if err != nil {
		return nil, mapTradingErr(err)
	}
	return orderPreviewToMap(result), nil
}

func (s *Service) PlaceOrder(ctx context.Context, portfolioID string, universe []bonds.BondRecord, isin, direction string, lots int, pricePct float64, figi, suggestionID *string) (map[string]any, error) {
	suggestion := ""
	if suggestionID != nil {
		suggestion = *suggestionID
	}
	result, err := s.orders.PlaceOrder(ctx, portfolioID, universe, isin, trading.OrderDirection(direction), lots, pricePct, figi, suggestion)
	if err != nil {
		return nil, mapTradingErr(err)
	}
	return placeOrderToMap(result), nil
}

func (s *Service) CancelOrder(ctx context.Context, portfolioID, orderID string) error {
	return mapTradingErr(s.orders.CancelOrder(ctx, portfolioID, orderID))
}

func (s *Service) PreviewSellPosition(ctx context.Context, portfolioID, isin string, universe []bonds.BondRecord, lots int, pricePct float64, today time.Time) (map[string]any, error) {
	result, err := s.sell.PreviewSellPosition(ctx, portfolioID, isin, universe, lots, pricePct, today)
	if err != nil {
		return nil, mapTradingErr(err)
	}
	return sellPreviewToMap(result), nil
}

func (s *Service) GetSellQuote(ctx context.Context, portfolioID, isin string, universe []bonds.BondRecord) (map[string]any, error) {
	result, err := s.sell.GetSellQuote(ctx, portfolioID, isin, universe)
	if err != nil {
		return nil, mapTradingErr(err)
	}
	return map[string]any{
		"market_price_pct":   result.MarketPricePct,
		"suggested_price_pct": result.SuggestedPricePct,
		"available_lots":   result.AvailableLots,
		"sell_buffer_label": result.SellBufferLabel,
	}, nil
}

func (s *Service) GetPerformance(ctx context.Context, portfolioID string) (map[string]any, error) {
	return s.advise.GetPerformance(ctx, portfolioID)
}

func (s *Service) GetAccountOperations(ctx context.Context, portfolioID string) ([]trading.BrokerOperation, error) {
	return s.advise.GetAccountOperations(ctx, portfolioID)
}

var _ application.TradingService = (*Service)(nil)

func mapAttachErr(err error) error {
	if err == nil {
		return nil
	}
	if err.Error() == "portfolio not found" {
		return application.ErrPortfolioNotFound
	}
	return err
}

func mapDeployErr(err error) error {
	if err == nil {
		return nil
	}
	var conflict DeploySessionConflictError
	if errors.As(err, &conflict) {
		return application.DeploySessionConflictError{Message: conflict.Message}
	}
	var notFound DeploySessionNotFoundError
	if errors.As(err, &notFound) {
		return application.DeploySessionNotFoundError{Message: notFound.Message}
	}
	var empty DeploySessionEmptyError
	if errors.As(err, &empty) {
		return application.DeploySessionEmptyError{Message: empty.Message}
	}
	if errors.Is(err, application.ErrPortfolioNotFound) {
		return err
	}
	if err.Error() == "portfolio not found" || err.Error() == "portfolio is not in trading mode" {
		return application.ErrPortfolioNotFound
	}
	return err
}

func orderPreviewToMap(r OrderPreviewResult) map[string]any {
	return map[string]any{
		"order_lots": r.OrderLots, "order_bonds": r.OrderBonds, "lot_size": r.LotSize,
		"order_price_pct": r.OrderPricePct, "clean_amount_rub": r.CleanAmountRub,
		"aci_rub_per_bond": r.AciRubPerBond, "local_total_amount_rub": r.LocalTotalAmountRub,
		"broker_clean_amount_rub": r.BrokerCleanAmountRub, "broker_aci_amount_rub": r.BrokerAciAmountRub,
		"broker_total_amount_rub": r.BrokerTotalAmountRub, "broker_commission_rub": r.BrokerCommissionRub,
		"money_rub": r.MoneyRub, "sufficient_cash": r.SufficientCash, "preview_source": r.PreviewSource,
		"market_price_pct": r.MarketPricePct, "face_value_rub": r.FaceValueRub,
	}
}

func placeOrderToMap(r PlaceOrderResult) map[string]any {
	return map[string]any{
		"order_id": r.OrderID, "status": r.Status, "request_uid": r.RequestUID,
		"lots_requested": r.LotsRequested, "lots_executed": r.LotsExecuted,
		"total_order_amount_rub": r.TotalOrderAmountRub, "initial_commission_rub": r.InitialCommissionRub,
	}
}

func sellPreviewToMap(r SellPositionPreviewResult) map[string]any {
	return map[string]any{
		"order_lots": r.OrderLots, "order_bonds": r.OrderBonds, "lot_size": r.LotSize,
		"order_price_pct": r.OrderPricePct, "clean_amount_rub": r.CleanAmountRub,
		"aci_rub_per_bond": r.AciRubPerBond, "local_total_amount_rub": r.LocalTotalAmountRub,
		"broker_clean_amount_rub": r.BrokerCleanAmountRub, "broker_aci_amount_rub": r.BrokerAciAmountRub,
		"broker_total_amount_rub": r.BrokerTotalAmountRub, "broker_commission_rub": r.BrokerCommissionRub,
		"money_rub": r.MoneyRub, "sufficient_cash": r.SufficientCash, "preview_source": r.PreviewSource,
		"available_lots": r.AvailableLots, "sufficient_lots": r.SufficientLots,
		"suggested_price_pct": r.SuggestedPricePct,
	}
}

// brokerClientFactory is overridden in broker_client.go.
var newBrokerClient = defaultBrokerClient

func defaultBrokerClient(token string, kind trading.AccountKind) trading.BrokerClient {
	return nil
}

func toBrokerSnapshot(snapshot trading.InfraAccountSnapshot) trading.BrokerSnapshot {
	// Avoid circular import from tinvest in tests; real impl in broker_client.go.
	if fn := brokerSnapshotFromInfra; fn != nil {
		return fn(snapshot)
	}
	return trading.BrokerSnapshot{}
}

var brokerSnapshotFromInfra func(trading.InfraAccountSnapshot) trading.BrokerSnapshot
