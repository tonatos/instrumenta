package trading

import (
	"github.com/tonatos/instrumenta/backend/internal/domain/trading"
	"github.com/tonatos/instrumenta/backend/internal/infrastructure/tinvest"
)

func init() {
	newBrokerClient = func(token string, kind trading.AccountKind) trading.BrokerClient {
		return tinvest.NewSDKClient(token, kind)
	}
	brokerSnapshotFromInfra = tinvest.ToBrokerSnapshot
}
