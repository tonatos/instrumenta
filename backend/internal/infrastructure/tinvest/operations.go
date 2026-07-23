package tinvest

import (
	"context"
	"strings"
	"time"

	"github.com/russianinvestments/invest-api-go-sdk/investgo"
	pb "github.com/russianinvestments/invest-api-go-sdk/proto"
	"github.com/tonatos/instrumenta/backend/internal/domain/shared"
	"github.com/tonatos/instrumenta/backend/internal/domain/trading"
)

func (c *SDKClient) GetAccountOperations(kind trading.AccountKind, accountID string, fromDate time.Time) ([]trading.InfraOperationRecord, error) {
	if err := c.configured(); err != nil {
		return nil, err
	}
	ctx := context.Background()
	client, err := c.connect(ctx)
	if err != nil {
		return nil, err
	}

	from := fromDate.UTC()
	to := time.Now().UTC()
	records := make([]trading.InfraOperationRecord, 0)
	cursor := ""

	for {
		req := &investgo.GetOperationsByCursorRequest{
			AccountId: accountID,
			From:      from,
			To:        to,
			Cursor:    cursor,
			Limit:     200,
		}
		var resp *investgo.GetOperationsByCursorResponse
		if isSandbox(kind) {
			resp, err = client.NewSandboxServiceClient().GetSandboxOperationsByCursor(req)
		} else {
			resp, err = client.NewOperationsServiceClient().GetOperationsByCursor(req)
		}
		if err != nil {
			return nil, mapRPCError(err, accountID)
		}
		for _, item := range resp.GetItems() {
			records = append(records, operationToRecord(item))
		}
		if !resp.GetHasNext() || resp.GetNextCursor() == "" {
			break
		}
		cursor = resp.GetNextCursor()
	}
	return records, nil
}

func operationToRecord(item *pb.OperationItem) trading.InfraOperationRecord {
	var date time.Time
	if item.GetDate() != nil {
		date = item.GetDate().AsTime()
	}
	var pricePct *shared.PriceUnitPct
	if item.GetPrice() != nil {
		v := shared.PriceUnitPct(item.GetPrice().ToFloat())
		pricePct = &v
	}
	return trading.InfraOperationRecord{
		ID:             item.GetId(),
		Type:           item.GetType().String(),
		State:          item.GetState().String(),
		Date:           date,
		FIGI:           item.GetFigi(),
		InstrumentUID:  item.GetInstrumentUid(),
		InstrumentType: strings.ToLower(item.GetInstrumentType()),
		PaymentRub:     moneyValueToRub(item.GetPayment()),
		Quantity:       int(item.GetQuantity()),
		PricePct:       pricePct,
		CommissionRub:  moneyValueToRub(item.GetCommission()),
	}
}
