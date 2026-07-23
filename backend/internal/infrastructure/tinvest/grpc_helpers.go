package tinvest

import (
	"context"
	"strings"

	pb "github.com/russianinvestments/invest-api-go-sdk/proto"
	"github.com/tonatos/instrumenta/backend/internal/domain/shared"
	"github.com/tonatos/instrumenta/backend/internal/domain/trading"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

func mapRPCError(err error, accountID string) error {
	if err == nil {
		return nil
	}
	code := extractErrorCode(err)
	msg := status.Convert(err).Message()
	if code == "" {
		msg = err.Error()
	}
	switch code {
	case "50004":
		label := accountID
		if label == "" {
			label = "указанный"
		}
		return tradingErrorf(
			"Счёт %s не найден в T-Invest. Возможно, sandbox-счёт был пересоздан — перепривяжите портфель.",
			label,
		)
	case "30052":
		return tradingNotAvailablef(
			"Инструмент недоступен для торговли через API (код %s: %s)",
			code, msg,
		)
	}
	if code != "" {
		return tradingErrorf("T-Invest API: %s (код %s)", msg, code)
	}
	if st, ok := status.FromError(err); ok && st.Code() != codes.Unknown {
		return tradingErrorf("T-Invest API: %s", st.Message())
	}
	return tradingErrorf("T-Invest API: %v", err)
}

func extractErrorCode(err error) string {
	msg := status.Convert(err).Message()
	for _, part := range strings.Fields(msg) {
		if len(part) == 5 && strings.Count(part, "") == 0 {
			continue
		}
	}
	// Codes appear as "30052" in message or metadata description.
	for _, token := range strings.FieldsFunc(msg, func(r rune) bool {
		return r == ' ' || r == ',' || r == ':' || r == '(' || r == ')'
	}) {
		if len(token) == 5 && token[0] == '3' {
			allDigits := true
			for _, ch := range token {
				if ch < '0' || ch > '9' {
					allDigits = false
					break
				}
			}
			if allDigits {
				return token
			}
		}
	}
	return ""
}

func directionToProto(direction trading.OrderDirection) pb.OrderDirection {
	if direction == trading.OrderDirectionSell {
		return pb.OrderDirection_ORDER_DIRECTION_SELL
	}
	return pb.OrderDirection_ORDER_DIRECTION_BUY
}

func directionFromProto(direction pb.OrderDirection) trading.OrderDirection {
	if direction == pb.OrderDirection_ORDER_DIRECTION_SELL {
		return trading.OrderDirectionSell
	}
	return trading.OrderDirectionBuy
}

func orderInstrumentID(figi, instrumentUID string) (string, error) {
	if instrumentUID != "" {
		return instrumentUID, nil
	}
	if figi != "" {
		return figi, nil
	}
	return "", tradingErrorf("Не задан FIGI или instrument_uid для заявки")
}

func portfolioMoneyRub(portfolio *pb.PortfolioResponse) shared.Rub {
	if portfolio == nil {
		return 0
	}
	totalCurrencies := shared.Rub(0)
	if mv := portfolio.GetTotalAmountCurrencies(); mv != nil {
		if rub := moneyValueToRub(mv); rub != nil {
			totalCurrencies = *rub
		}
	}
	var rubInPositions float64
	var foreignCurrencyValue float64
	for _, pos := range portfolio.GetPositions() {
		if strings.ToLower(pos.GetInstrumentType()) != "currency" {
			continue
		}
		ticker := strings.ToUpper(pos.GetTicker())
		qty := 0.0
		if pos.GetQuantity() != nil {
			qty = pos.GetQuantity().ToFloat()
		}
		if strings.Contains(ticker, "RUB") {
			rubInPositions += qty
			continue
		}
		currentPrice := 0.0
		if pos.GetCurrentPrice() != nil {
			currentPrice = pos.GetCurrentPrice().ToFloat()
		}
		foreignCurrencyValue += qty * currentPrice
	}
	if rubInPositions > 0 {
		return shared.Rub(rubInPositions)
	}
	estimated := float64(totalCurrencies) - foreignCurrencyValue
	if estimated < 0 {
		estimated = 0
	}
	return shared.Rub(estimated)
}

func positionsBlockedRub(ctx context.Context, c *SDKClient, accountID string) shared.Rub {
	client, err := c.connect(ctx)
	if err != nil {
		return 0
	}
	resp, err := client.NewOperationsServiceClient().GetPositions(accountID)
	if err != nil {
		packageLogger.Debug("get_positions failed", "account_id", accountID, "error", err)
		return 0
	}
	var total float64
	for _, mv := range resp.GetBlocked() {
		cur := strings.ToLower(mv.GetCurrency())
		if cur != "" && cur != "rub" && cur != "rur" {
			continue
		}
		if rub := moneyValueToRub(mv); rub != nil {
			total += float64(*rub)
		}
	}
	return shared.Rub(total)
}

func classifyPosition(pos *pb.PortfolioPosition, nominalRub *float64) (string, *trading.InfraBondPosition, *trading.InfraOtherInstrument) {
	if pos == nil {
		return "skip", nil, nil
	}
	quantity := 0.0
	if pos.GetQuantity() != nil {
		quantity = pos.GetQuantity().ToFloat()
	}
	if quantity <= 0 {
		return "skip", nil, nil
	}
	instrumentType := strings.ToLower(pos.GetInstrumentType())
	if instrumentType == "currency" {
		ticker := strings.ToUpper(pos.GetTicker())
		if strings.Contains(ticker, "RUB") {
			return "skip", nil, nil
		}
		return "other", nil, &trading.InfraOtherInstrument{
			InstrumentType: "currency",
			FIGI:           pos.GetFigi(),
			Ticker:         pos.GetTicker(),
			Quantity:       int(quantity),
		}
	}
	if instrumentType == "bond" {
		var currentPriceRub, avgPriceRub *float64
		if pos.GetCurrentPrice() != nil {
			v := pos.GetCurrentPrice().ToFloat()
			currentPriceRub = &v
		}
		if pos.GetAveragePositionPrice() != nil {
			v := pos.GetAveragePositionPrice().ToFloat()
			avgPriceRub = &v
		}
		lotsRaw := 0.0
		if pos.GetQuantityLots() != nil {
			lotsRaw = pos.GetQuantityLots().ToFloat()
		}
		lots := int(quantity)
		if lotsRaw > 0 {
			lots = int(lotsRaw)
			if lots < 1 {
				lots = 1
			}
		} else if lots < 1 {
			lots = 1
		}
		blocked := 0
		if pos.GetBlockedLots() != nil {
			blocked = int(pos.GetBlockedLots().ToFloat())
		}
		return "bond", &trading.InfraBondPosition{
			FIGI:            pos.GetFigi(),
			InstrumentUID:   pos.GetInstrumentUid(),
			Ticker:          pos.GetTicker(),
			Quantity:        int(quantity),
			Lots:            lots,
			Blocked:         blocked,
			CurrentPricePct: bondPricePctFromRub(currentPriceRub, derefFloat(nominalRub)),
			CurrentNKDRub:   moneyValueToRub(pos.GetCurrentNkd()),
			AveragePricePct: bondPricePctFromRub(avgPriceRub, derefFloat(nominalRub)),
		}, nil
	}
	return "other", nil, &trading.InfraOtherInstrument{
		InstrumentType: instrumentType,
		FIGI:           pos.GetFigi(),
		Ticker:         pos.GetTicker(),
		Quantity:       int(quantity),
	}
}

func derefFloat(v *float64) float64 {
	if v == nil {
		return 0
	}
	return *v
}
