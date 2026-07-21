package trading

import (
	"context"
	"fmt"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/domain/shared"
	"github.com/tonatos/bond-monitor/backend/internal/domain/trading"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/tinvest"
)

// SellPositionPreviewResult is a broker sell preview.
type SellPositionPreviewResult struct {
	OrderLots            int
	OrderBonds           int
	LotSize              int
	OrderPricePct        float64
	CleanAmountRub       float64
	AciRubPerBond        float64
	LocalTotalAmountRub  float64
	BrokerCleanAmountRub *float64
	BrokerAciAmountRub   *float64
	BrokerTotalAmountRub *float64
	BrokerCommissionRub  *float64
	MoneyRub             float64
	SufficientCash       bool
	PreviewSource        string
	AvailableLots        int
	SufficientLots       bool
	SuggestedPricePct    float64
}

// SellQuoteResult is a sell quote for UI.
type SellQuoteResult struct {
	MarketPricePct   float64
	SuggestedPricePct float64
	AvailableLots    int
	SellBufferLabel  string
}

// SellPositionUseCase handles sell preview and quotes.
type SellPositionUseCase struct {
	ctx    *Context
	broker *BrokerFacade
}

func NewSellPositionUseCase(ctx *Context, broker *BrokerFacade) *SellPositionUseCase {
	return &SellPositionUseCase{ctx: ctx, broker: broker}
}

func (u *SellPositionUseCase) PreviewSellPosition(ctx context.Context, portfolioID, isin string, universe []bonds.BondRecord, lots int, pricePct float64, today time.Time) (SellPositionPreviewResult, error) {
	_ = today
	p, err := u.ctx.GetTradingPortfolio(ctx, portfolioID)
	if err != nil {
		return SellPositionPreviewResult{}, mapTradingErr(err)
	}
	kind := *p.AccountKind
	accountID := *p.AccountID
	snapshot, err := u.broker.GetAccountSnapshot(ctx, kind, accountID)
	if err != nil {
		return SellPositionPreviewResult{}, err
	}
	brokerSnapshot := tinvest.ToBrokerSnapshot(snapshot)
	figi, availableLots := findHoldingLots(brokerSnapshot, universe, isin)
	if availableLots <= 0 {
		return SellPositionPreviewResult{}, fmt.Errorf("На счёте нет лотов для продажи")
	}
	if lots > availableLots {
		return SellPositionPreviewResult{}, fmt.Errorf("Недостаточно лотов: доступно %d", availableLots)
	}
	bond := bondByISIN(universe, isin)
	faceValue, lotSize, aci := sellInstrumentMeta(bond, brokerSnapshot, figi)
	buffer := trading.SellLimitPriceBuffer(p.AccountKind)
	market := marketPricePct(bond, brokerSnapshot, figi)
	suggested := float64(trading.SuggestedSellLimitPricePct(market, buffer))
	clean := float64(lots*lotSize) * faceValue * pricePct / 100
	localTotal := float64(shared.OrderAmountRub(shared.PriceUnitPct(pricePct), faceValue, lotSize, shared.Lots(lots), aci))
	result := SellPositionPreviewResult{
		OrderLots: lots, OrderBonds: lots * lotSize, LotSize: lotSize, OrderPricePct: pricePct,
		CleanAmountRub: clean, AciRubPerBond: aci, LocalTotalAmountRub: localTotal,
		MoneyRub: float64(snapshot.MoneyRub), SufficientCash: true, PreviewSource: "moex",
		AvailableLots: availableLots, SufficientLots: lots <= availableLots, SuggestedPricePct: suggested,
	}
	if figi != "" {
		instrumentUID := positionInstrumentUID(brokerSnapshot, figi)
		preview, err := u.broker.PreviewOrderPrice(ctx, kind, accountID, figi, instrumentUID, trading.OrderDirectionSell, shared.Lots(lots), shared.PriceUnitPct(pricePct))
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

func (u *SellPositionUseCase) GetSellQuote(ctx context.Context, portfolioID, isin string, universe []bonds.BondRecord) (SellQuoteResult, error) {
	p, err := u.ctx.GetTradingPortfolio(ctx, portfolioID)
	if err != nil {
		return SellQuoteResult{}, mapTradingErr(err)
	}
	kind := *p.AccountKind
	accountID := *p.AccountID
	snapshot, err := u.broker.GetAccountSnapshot(ctx, kind, accountID)
	if err != nil {
		return SellQuoteResult{}, err
	}
	brokerSnapshot := tinvest.ToBrokerSnapshot(snapshot)
	figi, availableLots := findHoldingLots(brokerSnapshot, universe, isin)
	if availableLots <= 0 {
		return SellQuoteResult{}, fmt.Errorf("На счёте нет лотов для продажи")
	}
	bond := bondByISIN(universe, isin)
	buffer := trading.SellLimitPriceBuffer(p.AccountKind)
	market := marketPricePct(bond, brokerSnapshot, figi)
	suggested := float64(trading.SuggestedSellLimitPricePct(market, buffer))
	return SellQuoteResult{
		MarketPricePct: market, SuggestedPricePct: suggested, AvailableLots: availableLots,
		SellBufferLabel: trading.FormatBuyLimitBufferLabel(buffer),
	}, nil
}

func findHoldingLots(snapshot trading.BrokerSnapshot, universe []bonds.BondRecord, isin string) (string, int) {
	bond := bondByISIN(universe, isin)
	if bond != nil && bond.FIGI != "" {
		if pos, ok := snapshot.BondPositions[bond.FIGI]; ok {
			return bond.FIGI, pos.Lots
		}
	}
	for figi, pos := range snapshot.BondPositions {
		for _, h := range trading.BuildHoldings(snapshot, universe) {
			if h.FIGI == figi && h.ISIN == isin {
				return figi, pos.Lots
			}
		}
	}
	return "", 0
}

func bondByISIN(universe []bonds.BondRecord, isin string) *bonds.BondRecord {
	for i := range universe {
		if universe[i].ISIN == isin {
			return &universe[i]
		}
	}
	return nil
}

func sellInstrumentMeta(bond *bonds.BondRecord, snapshot trading.BrokerSnapshot, figi string) (faceValue float64, lotSize int, aci float64) {
	faceValue = 1000
	lotSize = 1
	if bond != nil {
		faceValue = bond.FaceValue
		lotSize = bond.LotSize
		if bond.AccruedInterest != nil {
			aci = *bond.AccruedInterest
		}
	}
	if figi != "" {
		if pos, ok := snapshot.BondPositions[figi]; ok {
			if lotSize <= 0 && pos.Lots > 0 {
				lotSize = max(1, pos.Quantity/max(1, pos.Lots))
			}
			if aci == 0 && pos.CurrentNKDRub != nil {
				aci = float64(*pos.CurrentNKDRub)
			}
		}
	}
	return faceValue, lotSize, aci
}

func marketPricePct(bond *bonds.BondRecord, snapshot trading.BrokerSnapshot, figi string) float64 {
	if figi != "" {
		if pos, ok := snapshot.BondPositions[figi]; ok && pos.CurrentPricePct != nil {
			return float64(*pos.CurrentPricePct)
		}
	}
	if bond != nil && bond.LastPrice != nil && *bond.LastPrice > 0 {
		return *bond.LastPrice
	}
	return 100
}

func positionInstrumentUID(snapshot trading.BrokerSnapshot, figi string) string {
	if pos, ok := snapshot.BondPositions[figi]; ok {
		return pos.InstrumentUID
	}
	return ""
}
