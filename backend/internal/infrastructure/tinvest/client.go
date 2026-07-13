package tinvest

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/domain/trading"
)

func (c *SDKClient) MakeRequestUID(accountID, figi, direction string, lots int, orderKey, salt string) string {
	raw := fmt.Sprintf("%s|%s|%s|%d|%s|%s", accountID, figi, direction, lots, orderKey, salt)
	digest := sha256.Sum256([]byte(raw))
	hexDigest := hex.EncodeToString(digest[:])
	return fmt.Sprintf(
		"%s-%s-%s-%s-%s",
		hexDigest[0:8], hexDigest[8:12], hexDigest[12:16], hexDigest[16:20], hexDigest[20:32],
	)
}

// ReadClient enriches bonds from T-Invest metadata.
type ReadClient struct {
	cache *bondsDataCache
}

// NewReadClient creates a bond enricher backed by T-Invest read API.
func NewReadClient(token string) *ReadClient {
	r := &ReadClient{}
	if token != "" {
		r.cache = newBondsDataCache(token)
	}
	return r
}

func (r *ReadClient) EnrichBonds(bs []bonds.BondRecord) []bonds.BondRecord {
	if r.cache == nil {
		return applyFallbackTradeFlags(bs)
	}
	return enrichBondsFromAPI(context.Background(), r.cache, bs)
}

func (r *ReadClient) EnrichBondDetail(bond *bonds.BondRecord) {
	if bond == nil {
		return
	}
	if r.cache == nil {
		applyFallbackTradeFlag(bond)
		return
	}
	enrichBondDetailMetadata(context.Background(), r.cache.api, bond)
}

func (r *ReadClient) GetCouponSchedule(figi string) []bonds.CouponPayment {
	if r.cache == nil || figi == "" {
		return nil
	}
	return fetchCouponSchedule(context.Background(), r.cache.api, figi)
}

func applyFallbackTradeFlags(bs []bonds.BondRecord) []bonds.BondRecord {
	for i := range bs {
		applyFallbackTradeFlag(&bs[i])
	}
	return bs
}

func applyFallbackTradeFlag(bond *bonds.BondRecord) {
	if bond.APITradeAvailableFlag != nil {
		return
	}
	price := bond.PricePerLotRub()
	if bond.ISIN == "" || price == nil || *price <= 0 {
		return
	}
	tradable := true
	bond.APITradeAvailableFlag = &tradable
}

var _ bonds.Enricher = (*ReadClient)(nil)
var _ trading.BrokerClient = (*SDKClient)(nil)
