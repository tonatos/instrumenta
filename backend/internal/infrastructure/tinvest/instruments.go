package tinvest

import (
	"context"
	"strings"

	"github.com/russianinvestments/invest-api-go-sdk/investgo"
	"github.com/tonatos/bond-monitor/backend/internal/domain/shared"
	"github.com/tonatos/bond-monitor/backend/internal/domain/trading"
)

func (c *SDKClient) fetchBondNominal(ctx context.Context, figi, instrumentUID string) (float64, error) {
	client, err := c.connect(ctx)
	if err != nil {
		return 0, err
	}
	inst := client.NewInstrumentsServiceClient()
	lookups := make([]struct {
		byUID bool
		id    string
	}, 0, 2)
	if instrumentUID != "" {
		lookups = append(lookups, struct {
			byUID bool
			id    string
		}{true, instrumentUID})
	}
	if figi != "" {
		lookups = append(lookups, struct {
			byUID bool
			id    string
		}{false, figi})
	}
	for _, lookup := range lookups {
		var resp *investgo.BondResponse
		var err error
		if lookup.byUID {
			resp, err = inst.BondByUid(lookup.id)
		} else {
			resp, err = inst.BondByFigi(lookup.id)
		}
		if err != nil {
			packageLogger.Debug("bond_by failed", "id", lookup.id, "error", err)
			continue
		}
		if rub := moneyValueToRub(resp.GetInstrument().GetNominal()); rub != nil && *rub > 0 {
			return float64(*rub), nil
		}
	}
	return 0, tradingErrorf("bond nominal not found for figi=%s uid=%s", figi, instrumentUID)
}

func (c *SDKClient) ResolveFIGIForISIN(isin string) (string, error) {
	if err := c.configured(); err != nil {
		return "", err
	}
	isin = strings.TrimSpace(isin)
	if isin == "" {
		return "", tradingErrorf("ISIN is empty")
	}
	ctx := context.Background()
	client, err := c.connect(ctx)
	if err != nil {
		return "", err
	}
	resp, err := client.NewInstrumentsServiceClient().FindInstrument(isin)
	if err != nil {
		return "", mapRPCError(err, "")
	}
	for _, ins := range resp.GetInstruments() {
		if strings.EqualFold(ins.GetIsin(), isin) && ins.GetFigi() != "" {
			return ins.GetFigi(), nil
		}
	}
	return "", tradingErrorf("FIGI not found for ISIN %s", isin)
}

func (c *SDKClient) CheckTradeAvailable(figi, instrumentUID string) (*trading.TradeInstrument, error) {
	if err := c.configured(); err != nil {
		return nil, err
	}
	ctx := context.Background()
	client, err := c.connect(ctx)
	if err != nil {
		return nil, err
	}
	bond, err := c.lookupBond(ctx, client, figi, instrumentUID)
	if err != nil {
		return nil, err
	}
	ins := bond.GetInstrument()
	if !ins.GetApiTradeAvailableFlag() {
		return nil, tradingNotAvailablef("облигация %s недоступна для торговли через API", ins.GetTicker())
	}
	lotSize := int(ins.GetLot())
	if lotSize < 1 {
		lotSize = 1
	}
	return &trading.TradeInstrument{
		FIGI:          ins.GetFigi(),
		InstrumentUID: ins.GetUid(),
		LotSize:       lotSize,
	}, nil
}

func (c *SDKClient) EnsureOrderInstrument(figi, instrumentUID, isin string, direction trading.OrderDirection) (trading.TradeInstrument, error) {
	_ = direction
	if err := c.configured(); err != nil {
		return trading.TradeInstrument{}, err
	}
	if figi == "" && instrumentUID == "" && isin != "" {
		var err error
		figi, err = c.ResolveFIGIForISIN(isin)
		if err != nil {
			return trading.TradeInstrument{}, err
		}
	}
	trade, err := c.CheckTradeAvailable(figi, instrumentUID)
	if err != nil {
		return trading.TradeInstrument{}, err
	}
	if trade == nil {
		return trading.TradeInstrument{}, tradingNotAvailablef("инструмент недоступен для торговли")
	}
	return *trade, nil
}

func (c *SDKClient) GetLastPricePct(figi string) (*float64, error) {
	if err := c.configured(); err != nil {
		return nil, err
	}
	if figi == "" {
		return nil, tradingErrorf("FIGI is empty")
	}
	ctx := context.Background()
	client, err := c.connect(ctx)
	if err != nil {
		return nil, err
	}
	resp, err := client.NewMarketDataServiceClient().GetLastPrices([]string{figi})
	if err != nil {
		return nil, mapRPCError(err, "")
	}
	prices := resp.GetLastPrices()
	if len(prices) == 0 || prices[0].GetPrice() == nil {
		return nil, nil
	}
	nominal, err := c.fetchBondNominal(ctx, figi, "")
	if err != nil {
		// Last price for bonds may already be in % — return raw quotation.
		v := prices[0].GetPrice().ToFloat()
		return &v, nil
	}
	priceRub := prices[0].GetPrice().ToFloat()
	pct := float64(shared.BondCleanPricePctFromRub(priceRub, nominal))
	return &pct, nil
}

func (c *SDKClient) lookupBond(ctx context.Context, client *investgo.Client, figi, instrumentUID string) (*investgo.BondResponse, error) {
	_ = ctx
	inst := client.NewInstrumentsServiceClient()
	if instrumentUID != "" {
		if resp, err := inst.BondByUid(instrumentUID); err == nil {
			return resp, nil
		}
	}
	if figi != "" {
		if resp, err := inst.BondByFigi(figi); err == nil {
			return resp, nil
		}
	}
	return nil, tradingErrorf("bond not found figi=%s uid=%s", figi, instrumentUID)
}
