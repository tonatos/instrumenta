package trading

import (
	"github.com/tonatos/bond-monitor/backend/internal/domain/trading"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/tinvest"
)

func init() {
	newBrokerClient = func(token string, kind trading.AccountKind) trading.BrokerClient {
		return tinvest.NewSDKClient(token, kind)
	}
	brokerSnapshotFromInfra = tinvest.ToBrokerSnapshot
}
