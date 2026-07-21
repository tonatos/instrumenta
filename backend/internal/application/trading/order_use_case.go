package trading

import (
	"context"
	"fmt"
	"time"

	appportfolio "github.com/tonatos/bond-monitor/backend/internal/application/portfolio"
	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	domainPortfolio "github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
	"github.com/tonatos/bond-monitor/backend/internal/domain/shared"
	"github.com/tonatos/bond-monitor/backend/internal/domain/trading"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/tinvest"
)

// OrderPreviewResult is a broker order cost preview.
type OrderPreviewResult struct {
	OrderLots              int
	OrderBonds             int
	LotSize                int
	OrderPricePct          float64
	CleanAmountRub         float64
	AciRubPerBond          float64
	LocalTotalAmountRub    float64
	BrokerCleanAmountRub   *float64
	BrokerAciAmountRub     *float64
	BrokerTotalAmountRub   *float64
	BrokerCommissionRub    *float64
	MoneyRub               float64
	SufficientCash         bool
	PreviewSource          string
	MarketPricePct         *float64
	FaceValueRub           float64
}

// PlaceOrderResult is the result of submitting an order.
type PlaceOrderResult struct {
	OrderID              string
	Status               string
	RequestUID           string
	LotsRequested        int
	LotsExecuted         int
	TotalOrderAmountRub  *float64
	InitialCommissionRub *float64
}

// OrderUseCase handles order preview, place and cancel.
type OrderUseCase struct {
	ctx            *Context
	broker         *BrokerFacade
	deploySessions *DeploySessionUseCase
}

func NewOrderUseCase(ctx *Context, broker *BrokerFacade, deploySessions *DeploySessionUseCase) *OrderUseCase {
	return &OrderUseCase{ctx: ctx, broker: broker, deploySessions: deploySessions}
}

func (u *OrderUseCase) PreviewOrder(ctx context.Context, portfolioID string, universe []bonds.BondRecord, isin string, direction trading.OrderDirection, lots int, pricePct float64, figi *string) (OrderPreviewResult, error) {
	p, err := u.ctx.GetTradingPortfolio(ctx, portfolioID)
	if err != nil {
		return OrderPreviewResult{}, err
	}
	kind := *p.AccountKind
	accountID := *p.AccountID
	snapshot, err := u.broker.GetAccountSnapshot(ctx, kind, accountID)
	if err != nil {
		return OrderPreviewResult{}, err
	}
	var bond *bonds.BondRecord
	for i := range universe {
		if universe[i].ISIN == isin {
			bond = &universe[i]
			break
		}
	}
	faceValue := 1000.0
	lotSize := 1
	aci := 0.0
	if bond != nil {
		faceValue = bond.FaceValue
		lotSize = bond.LotSize
		if bond.AccruedInterest != nil {
			aci = *bond.AccruedInterest
		}
	}
	clean := float64(lots*lotSize) * faceValue * pricePct / 100
	localTotal := float64(shared.OrderAmountRub(shared.PriceUnitPct(pricePct), faceValue, lotSize, shared.Lots(lots), aci))
	result := OrderPreviewResult{
		OrderLots: lots, OrderBonds: lots * lotSize, LotSize: lotSize, OrderPricePct: pricePct,
		CleanAmountRub: clean, AciRubPerBond: aci, LocalTotalAmountRub: localTotal,
		MoneyRub: float64(snapshot.MoneyRub), SufficientCash: float64(snapshot.AvailableMoneyRub()) >= localTotal,
		FaceValueRub: faceValue, PreviewSource: "moex",
	}
	orderFIGI := derefString(figi)
	if orderFIGI == "" && bond != nil {
		orderFIGI = bond.FIGI
	}
	if orderFIGI != "" {
		preview, err := u.broker.PreviewOrderPrice(ctx, kind, accountID, orderFIGI, "", direction, shared.Lots(lots), shared.PriceUnitPct(pricePct))
		if err == nil {
			result.PreviewSource = "broker"
			result.BrokerCleanAmountRub = rubPtr(preview.CleanAmountRub)
			result.BrokerAciAmountRub = rubPtr(preview.AciAmountRub)
			result.BrokerTotalAmountRub = rubPtr(preview.TotalOrderAmountRub)
			result.BrokerCommissionRub = rubPtr(preview.ExecutedCommission)
		}
	}
	return result, nil
}

func (u *OrderUseCase) PlaceOrder(ctx context.Context, portfolioID string, universe []bonds.BondRecord, isin string, direction trading.OrderDirection, lots int, pricePct float64, figi *string, suggestionID string) (PlaceOrderResult, error) {
	p, err := u.ctx.GetTradingPortfolio(ctx, portfolioID)
	if err != nil {
		return PlaceOrderResult{}, err
	}
	kind := *p.AccountKind
	accountID := *p.AccountID
	trade, err := u.broker.EnsureOrderInstrument(ctx, kind, derefString(figi), "", isin, direction)
	if err != nil {
		return PlaceOrderResult{}, err
	}
	requestUID := u.broker.MakeRequestUID(ctx, kind, accountID, trade.FIGI, string(direction), lots, suggestionID, time.Now().UTC().Format(time.RFC3339))
	result, err := u.broker.PostLimitOrder(ctx, kind, accountID, trade.FIGI, trade.InstrumentUID, direction, shared.Lots(lots), shared.PriceUnitPct(pricePct), requestUID)
	if err != nil {
		return PlaceOrderResult{}, err
	}
	if u.deploySessions != nil && suggestionID != "" {
		if session, err := u.deploySessions.GetActive(ctx, portfolioID); err == nil && session != nil {
			if trading.FindSessionItem(*session, suggestionID) != nil {
				updated := trading.MarkItemPlaced(*session, suggestionID, result.OrderID)
				_, _ = u.deploySessions.SaveSession(ctx, updated)
			}
		}
	}
	return PlaceOrderResult{
		OrderID: result.OrderID, Status: result.ExecutionReportStatus, RequestUID: result.RequestUID,
		LotsRequested: result.LotsRequested, LotsExecuted: result.LotsExecuted,
		TotalOrderAmountRub: rubPtr(result.TotalOrderAmountRub), InitialCommissionRub: rubPtr(result.InitialCommissionRub),
	}, nil
}

func (u *OrderUseCase) CancelOrder(ctx context.Context, portfolioID, orderID string) error {
	p, err := u.ctx.GetTradingPortfolio(ctx, portfolioID)
	if err != nil {
		return err
	}
	return u.broker.CancelOrder(ctx, *p.AccountKind, *p.AccountID, orderID)
}

// AttachUseCase handles broker account attach/detach.
type AttachUseCase struct {
	ctx    *Context
	broker *BrokerFacade
	plans  *appportfolio.PlanUseCase
}

func NewAttachUseCase(ctx *Context, broker *BrokerFacade, plans *appportfolio.PlanUseCase) *AttachUseCase {
	return &AttachUseCase{ctx: ctx, broker: broker, plans: plans}
}

func (u *AttachUseCase) GetAccountPreview(ctx context.Context, portfolioID, accountID string, kind trading.AccountKind, universe []bonds.BondRecord) (map[string]any, error) {
	p, err := u.ctx.Repo().GetByID(ctx, portfolioID)
	if err != nil || p == nil {
		return nil, fmt.Errorf("portfolio not found")
	}
	snapshot, err := u.broker.GetAccountSnapshot(ctx, kind, accountID)
	if err != nil {
		return nil, err
	}
	linked, _ := u.ctx.FindLinkedPortfolio(ctx, accountID, kind, portfolioID)
	validation := trading.ValidateAttachSoft(tinvest.ToBrokerSnapshot(snapshot), *p, universe)
	if linked != nil {
		validation.CanAttach = false
		validation.Blockers = append([]string{fmt.Sprintf("Счёт уже привязан к портфелю «%s»", linked.Name)}, validation.Blockers...)
	}
	return map[string]any{
		"money_rub": float64(snapshot.MoneyRub), "can_attach": validation.CanAttach,
		"blockers": validation.Blockers, "warnings": validation.Warnings,
	}, nil
}

func (u *AttachUseCase) DetachAccount(ctx context.Context, portfolioID string) (domainPortfolio.Portfolio, error) {
	p, err := u.ctx.Repo().GetByID(ctx, portfolioID)
	if err != nil || p == nil {
		return domainPortfolio.Portfolio{}, fmt.Errorf("portfolio not found")
	}
	p.Mode = domainPortfolio.PortfolioModeSimulation
	p.AccountID = nil
	p.AccountKind = nil
	p.FrozenForecast = nil
	p.TradingStartedAt = nil
	return u.ctx.Repo().Save(ctx, *p)
}

func (u *AttachUseCase) AttachAccount(ctx context.Context, portfolioID, accountID string, kind trading.AccountKind, universe []bonds.BondRecord, keyRate, taxRate float64, today time.Time) (domainPortfolio.Portfolio, error) {
	p, err := u.ctx.Repo().GetByID(ctx, portfolioID)
	if err != nil || p == nil {
		return domainPortfolio.Portfolio{}, fmt.Errorf("portfolio not found")
	}
	linked, _ := u.ctx.FindLinkedPortfolio(ctx, accountID, kind, portfolioID)
	if linked != nil {
		return domainPortfolio.Portfolio{}, fmt.Errorf("Счёт уже привязан к портфелю «%s»", linked.Name)
	}
	snapshot, err := u.broker.GetAccountSnapshot(ctx, kind, accountID)
	if err != nil {
		return domainPortfolio.Portfolio{}, err
	}
	brokerSnapshot := tinvest.ToBrokerSnapshot(snapshot)
	_ = trading.ValidateAttachSoft(brokerSnapshot, *p, universe)
	for i := range p.Positions {
		if p.Positions[i].FIGI == nil || *p.Positions[i].FIGI == "" {
			figi, err := u.broker.ResolveFIGIForISIN(ctx, kind, p.Positions[i].ISIN)
			if err == nil && figi != "" {
				p.Positions[i].FIGI = &figi
			}
		}
	}
	ops, err := u.broker.GetAccountOperations(ctx, kind, accountID, OperationsFromDate(today))
	if err != nil {
		return domainPortfolio.Portfolio{}, err
	}
	policy := domainPortfolio.DurationPolicyForPortfolio(*p, domainPortfolio.RateScenarioHold)
	plan := u.plans.BuildForTrading(*p, brokerSnapshot, tinvest.ToBrokerOperations(ops), universe, today, keyRate, taxRate, policy)
	nowISO := time.Now().UTC().Format(time.RFC3339)
	p.Mode = domainPortfolio.PortfolioModeTrading
	p.AccountID = &accountID
	p.AccountKind = &kind
	p.TradingStartedAt = &nowISO
	p.FrozenForecast = &domainPortfolio.FrozenForecast{
		ExpectedXIRRPct:           plan.EffectiveAnnualReturnPct,
		ExpectedTotalNetProfitRub: plan.TotalNetProfitRub,
		ExpectedFinalValueRub:     plan.FinalPortfolioValueRub,
		FrozenInitialAmountRub:    plan.InvestedCapitalRub,
		HorizonDate:               p.HorizonDate,
		CreatedAt:                 nowISO,
	}
	holdings := trading.BuildHoldings(brokerSnapshot, universe)
	holdingISINs := make(map[string]struct{})
	for _, h := range holdings {
		if h.ISIN != "" {
			holdingISINs[h.ISIN] = struct{}{}
		}
	}
	if err := PrepareTradingRiskMonitoring(ctx, u.ctx, p, universe, holdingISINs); err != nil {
		return domainPortfolio.Portfolio{}, err
	}
	return u.ctx.Repo().Save(ctx, *p)
}

func (u *AttachUseCase) ClearAccountForAttach(ctx context.Context, portfolioID, accountID string, kind trading.AccountKind, payInRub *float64, universe []bonds.BondRecord) (map[string]any, error) {
	if kind != trading.AccountKindSandbox {
		return nil, fmt.Errorf("Освобождение счёта доступно только в песочнице")
	}
	p, err := u.ctx.Repo().GetByID(ctx, portfolioID)
	if err != nil || p == nil {
		return nil, fmt.Errorf("portfolio not found")
	}
	snapshot, err := u.broker.GetAccountSnapshot(ctx, kind, accountID)
	if err != nil {
		return nil, err
	}
	activeAccountID := accountID
	payIn := p.InitialAmountRub
	if payInRub != nil {
		payIn = *payInRub
	}
	if len(snapshot.BondPositions) > 0 || len(snapshot.OtherInstruments) > 0 {
		_ = u.broker.CloseSandboxAccount(ctx, activeAccountID)
		newID, err := u.broker.OpenSandboxAccount(ctx, "bond-monitor-cleared")
		if err != nil {
			return nil, err
		}
		if _, err := u.broker.SandboxPayIn(ctx, newID, shared.Rub(payIn)); err != nil {
			return nil, err
		}
		activeAccountID = newID
		snapshot, err = u.broker.GetAccountSnapshot(ctx, kind, activeAccountID)
		if err != nil {
			return nil, err
		}
	}
	linked, _ := u.ctx.FindLinkedPortfolio(ctx, activeAccountID, kind, portfolioID)
	validation := trading.ValidateAttachSoft(tinvest.ToBrokerSnapshot(snapshot), *p, universe)
	if linked != nil {
		validation.CanAttach = false
		validation.Blockers = append([]string{fmt.Sprintf("Счёт уже привязан к портфелю «%s»", linked.Name)}, validation.Blockers...)
	}
	preview := map[string]any{
		"money_rub": float64(snapshot.MoneyRub), "can_attach": validation.CanAttach,
		"blockers": validation.Blockers, "warnings": validation.Warnings,
		"account_id": activeAccountID, "sold_count": 0, "sold": []any{},
	}
	if activeAccountID != accountID {
		preview["account_replaced"] = map[string]string{"old_id": accountID, "new_id": activeAccountID}
		preview["reset_note"] = fmt.Sprintf("Счёт пересоздан с пополнением %.0f ₽", payIn)
	}
	return preview, nil
}

func derefString(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}

func rubPtr(r *shared.Rub) *float64 {
	if r == nil {
		return nil
	}
	v := float64(*r)
	return &v
}
