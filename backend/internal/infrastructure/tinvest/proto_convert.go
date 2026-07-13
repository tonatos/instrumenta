package tinvest

import (
	"strings"
	"time"

	pb "github.com/russianinvestments/invest-api-go-sdk/proto"
	"github.com/tonatos/bond-monitor/backend/internal/domain/shared"
)

func moneyValueToRub(mv *pb.MoneyValue) *shared.Rub {
	if mv == nil {
		return nil
	}
	cur := strings.ToLower(mv.GetCurrency())
	if cur != "" && cur != "rub" && cur != "rur" {
		return nil
	}
	v := mv.ToFloat()
	r := shared.Rub(v)
	return &r
}

func quotationToFloat(q *pb.Quotation) *float64 {
	if q == nil {
		return nil
	}
	v := q.ToFloat()
	if v == 0 {
		return nil
	}
	return &v
}

func quotationToPricePct(q *pb.Quotation) *shared.PriceUnitPct {
	if f := quotationToFloat(q); f != nil {
		p := shared.PriceUnitPct(*f)
		return &p
	}
	return nil
}

func bondPricePctFromRub(priceRub *float64, nominal float64) *shared.PriceUnitPct {
	if priceRub == nil || nominal <= 0 {
		return nil
	}
	p := shared.BondCleanPricePctFromRub(*priceRub, nominal)
	return &p
}

func pbQuotationFromShared(q shared.Quotation) *pb.Quotation {
	return &pb.Quotation{Units: q.Units, Nano: int32(q.Nano)}
}

func pbQuotationFromPct(pricePct shared.PriceUnitPct, faceValue float64) *pb.Quotation {
	q := shared.BondCleanPriceQuotation(pricePct, faceValue)
	return pbQuotationFromShared(q)
}

func rubPtr(v *shared.Rub) *shared.Rub {
	return v
}

func protoTime(t *time.Time) time.Time {
	if t == nil {
		return time.Time{}
	}
	return *t
}
