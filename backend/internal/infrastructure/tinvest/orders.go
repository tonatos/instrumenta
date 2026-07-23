package tinvest

import (
	"context"
	"math"
	"time"

	"github.com/russianinvestments/invest-api-go-sdk/investgo"
	pb "github.com/russianinvestments/invest-api-go-sdk/proto"
	"github.com/tonatos/instrumenta/backend/internal/domain/shared"
	"github.com/tonatos/instrumenta/backend/internal/domain/trading"
)

var activeOrderStatuses = map[string]struct{}{
	"EXECUTION_REPORT_STATUS_NEW":              {},
	"EXECUTION_REPORT_STATUS_PARTIALLYFILL":    {},
	"EXECUTION_REPORT_STATUS_PENDING_CANCEL": {},
}

func (c *SDKClient) PreviewOrderPrice(
	kind trading.AccountKind,
	accountID, figi, instrumentUID string,
	direction trading.OrderDirection,
	lots shared.Lots,
	pricePct shared.PriceUnitPct,
) (trading.InfraOrderPricePreview, error) {
	if err := c.configured(); err != nil {
		return trading.InfraOrderPricePreview{}, err
	}
	ctx := context.Background()
	client, err := c.connect(ctx)
	if err != nil {
		return trading.InfraOrderPricePreview{}, err
	}
	instrumentID, err := orderInstrumentID(figi, instrumentUID)
	if err != nil {
		return trading.InfraOrderPricePreview{}, err
	}
	nominal, err := c.fetchBondNominal(ctx, figi, instrumentUID)
	if err != nil {
		return trading.InfraOrderPricePreview{}, err
	}
	price := pbQuotationFromPct(pricePct, nominal)
	resp, err := client.NewOrdersServiceClient().GetOrderPrice(
		accountID,
		instrumentID,
		price,
		directionToProto(direction),
		int64(lots),
	)
	if err != nil {
		return trading.InfraOrderPricePreview{}, mapRPCError(err, accountID)
	}
	var aci *shared.Rub
	if extra := resp.GetExtraBond(); extra != nil {
		aci = moneyValueToRub(extra.GetAciValue())
	}
	return trading.InfraOrderPricePreview{
		LotsRequested:       int(resp.GetLotsRequested()),
		CleanAmountRub:      moneyValueToRub(resp.GetInitialOrderAmount()),
		AciAmountRub:        aci,
		TotalOrderAmountRub: moneyValueToRub(resp.GetTotalOrderAmount()),
		ExecutedCommission:  moneyValueToRub(resp.GetExecutedCommission()),
	}, nil
}

func (c *SDKClient) PostLimitOrder(
	kind trading.AccountKind,
	accountID, figi, instrumentUID string,
	direction trading.OrderDirection,
	lots shared.Lots,
	pricePct shared.PriceUnitPct,
	requestUID string,
) (trading.InfraPostOrderResult, error) {
	if err := c.configured(); err != nil {
		return trading.InfraPostOrderResult{}, err
	}
	ctx := context.Background()
	client, err := c.connect(ctx)
	if err != nil {
		return trading.InfraPostOrderResult{}, err
	}
	instrumentID, err := orderInstrumentID(figi, instrumentUID)
	if err != nil {
		return trading.InfraPostOrderResult{}, err
	}
	nominal, err := c.fetchBondNominal(ctx, figi, instrumentUID)
	if err != nil {
		return trading.InfraPostOrderResult{}, err
	}
	estimated := shared.OrderAmountRub(pricePct, nominal, 1, lots, 0)
	if estimated > shared.MaxOrderAmountRub {
		return trading.InfraPostOrderResult{}, orderTooLargef(
			"Сумма заявки %.0f ₽ > %.0f ₽ (API требует SMS-подтверждения, через API не доступно). Разделите на несколько заявок.",
			float64(estimated), float64(shared.MaxOrderAmountRub),
		)
	}

	req := &investgo.PostOrderRequest{
		Quantity:     int64(lots),
		Price:        pbQuotationFromPct(pricePct, nominal),
		Direction:    directionToProto(direction),
		AccountId:    accountID,
		OrderType:    pb.OrderType_ORDER_TYPE_LIMIT,
		OrderId:      requestUID,
		InstrumentId: instrumentID,
		TimeInForce:  pb.TimeInForceType_TIME_IN_FORCE_DAY,
	}
	resp, err := client.NewOrdersServiceClient().PostOrder(req)
	if err != nil {
		code := extractErrorCode(err)
		if code == "30052" {
			return trading.InfraPostOrderResult{}, tradingNotAvailablef(
				"Облигация недоступна для торговли через API (код %s)", code,
			)
		}
		if code == "70002" {
			packageLogger.Warn("post_order retry after 70002", "request_uid", requestUID)
			resp, err = client.NewOrdersServiceClient().PostOrder(req)
		}
		if err != nil {
			if code == "30057" {
				return trading.InfraPostOrderResult{}, tradingErrorf(
					"Заявка с этим ключом идемпотентности уже была отправлена, но отчёт не найден. Повторите подтверждение — будет сгенерирован новый ключ.",
				)
			}
			return trading.InfraPostOrderResult{}, mapRPCError(err, accountID)
		}
	}
	return postOrderToResult(resp, requestUID), nil
}

func (c *SDKClient) PostMarketSellOrder(
	kind trading.AccountKind,
	accountID, figi, instrumentUID string,
	lots shared.Lots,
	requestUID string,
	referencePricePct *shared.PriceUnitPct,
	lotSize int,
) (trading.InfraPostOrderResult, error) {
	base := shared.PriceUnitPct(100)
	if referencePricePct != nil {
		base = *referencePricePct
	}
	sellPrice := shared.PriceUnitPct(math.Max(1, math.Round(float64(base)*0.97*10000)/10000))
	return c.PostLimitOrder(kind, accountID, figi, instrumentUID, trading.OrderDirectionSell, lots, sellPrice, requestUID)
}

func (c *SDKClient) GetOrderState(kind trading.AccountKind, accountID, orderID string) (trading.InfraOrderState, error) {
	if err := c.configured(); err != nil {
		return trading.InfraOrderState{}, err
	}
	ctx := context.Background()
	client, err := c.connect(ctx)
	if err != nil {
		return trading.InfraOrderState{}, err
	}
	priceType := pb.PriceType_PRICE_TYPE_CURRENCY
	resp, err := client.NewOrdersServiceClient().GetOrderState(accountID, orderID, priceType, nil)
	if err != nil {
		return trading.InfraOrderState{}, mapRPCError(err, accountID)
	}
	state := resp.OrderState
	nominal, _ := c.fetchBondNominal(ctx, state.GetFigi(), state.GetInstrumentUid())
	var face *float64
	if nominal > 0 {
		face = &nominal
	}
	return orderStateFromProto(state, face), nil
}

func (c *SDKClient) GetActiveOrders(kind trading.AccountKind, accountID string) ([]trading.InfraOrderState, error) {
	if err := c.configured(); err != nil {
		return nil, err
	}
	ctx := context.Background()
	client, err := c.connect(ctx)
	if err != nil {
		return nil, err
	}
	resp, err := client.NewOrdersServiceClient().GetOrders(accountID, nil)
	if err != nil {
		return nil, mapRPCError(err, accountID)
	}
	nominalCache := map[string]*float64{}
	orders := make([]trading.InfraOrderState, 0)
	for _, state := range resp.GetOrders() {
		statusName := state.GetExecutionReportStatus().String()
		if _, ok := activeOrderStatuses[statusName]; !ok {
			continue
		}
		figi := state.GetFigi()
		if _, ok := nominalCache[figi]; !ok {
			nominal, err := c.fetchBondNominal(ctx, figi, state.GetInstrumentUid())
			if err != nil {
				nominalCache[figi] = nil
			} else {
				nominalCache[figi] = &nominal
			}
		}
		orders = append(orders, orderStateFromProto(state, nominalCache[figi]))
	}
	return orders, nil
}

func (c *SDKClient) CancelOrder(kind trading.AccountKind, accountID, orderID string) error {
	if err := c.configured(); err != nil {
		return err
	}
	ctx := context.Background()
	client, err := c.connect(ctx)
	if err != nil {
		return err
	}
	_, err = client.NewOrdersServiceClient().CancelOrder(accountID, orderID, nil)
	if err != nil {
		packageLogger.Warn("cancel_order failed", "order_id", orderID, "error", err)
		return mapRPCError(err, accountID)
	}
	return nil
}

func postOrderToResult(resp *investgo.PostOrderResponse, requestUID string) trading.InfraPostOrderResult {
	if resp == nil || resp.PostOrderResponse == nil {
		return trading.InfraPostOrderResult{RequestUID: requestUID}
	}
	return trading.InfraPostOrderResult{
		OrderID:               resp.GetOrderId(),
		RequestUID:            requestUID,
		ExecutionReportStatus: resp.GetExecutionReportStatus().String(),
		LotsExecuted:          int(resp.GetLotsExecuted()),
		LotsRequested:         int(resp.GetLotsRequested()),
		TotalOrderAmountRub:   moneyValueToRub(resp.GetTotalOrderAmount()),
		InitialCommissionRub:  moneyValueToRub(resp.GetInitialCommission()),
	}
}

func orderStateFromProto(state *pb.OrderState, faceValue *float64) trading.InfraOrderState {
	if state == nil {
		return trading.InfraOrderState{}
	}
	var pricePct *shared.PriceUnitPct
	if state.GetInitialSecurityPrice() != nil {
		limitRub := state.GetInitialSecurityPrice().ToFloat()
		if faceValue != nil && *faceValue > 0 {
			p := shared.BondCleanPricePctFromRub(limitRub, *faceValue)
			pricePct = &p
		} else {
			p := shared.PriceUnitPct(limitRub)
			pricePct = &p
		}
	}
	var orderDate *time.Time
	if state.GetOrderDate() != nil {
		t := state.GetOrderDate().AsTime()
		orderDate = &t
	}
	return trading.InfraOrderState{
		OrderID:               state.GetOrderId(),
		RequestUID:            state.GetOrderRequestId(),
		FIGI:                  state.GetFigi(),
		Direction:             directionFromProto(state.GetDirection()),
		LotsRequested:         int(state.GetLotsRequested()),
		LotsExecuted:          int(state.GetLotsExecuted()),
		ExecutionReportStatus: state.GetExecutionReportStatus().String(),
		PricePct:              pricePct,
		TotalOrderAmountRub:   moneyValueToRub(state.GetTotalOrderAmount()),
		InitialCommissionRub:  moneyValueToRub(state.GetInitialCommission()),
		OrderDate:             orderDate,
	}
}
