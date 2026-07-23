package tinvest

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"github.com/russianinvestments/invest-api-go-sdk/investgo"
	"github.com/tonatos/instrumenta/backend/internal/domain/trading"
)

const (
	sandboxEndpoint    = "sandbox-invest-public-api.tbank.ru:443"
	productionEndpoint = "invest-public-api.tbank.ru:443"
	appName            = "instrumenta"
)

var packageLogger = slog.Default()

// SetLogger configures structured logging for the T-Invest client.
func SetLogger(l *slog.Logger) {
	if l != nil {
		packageLogger = l
	}
}

// SDKClient wraps T-Invest invest-api-go-sdk behind trading.BrokerClient.
type SDKClient struct {
	token string
	kind  trading.AccountKind
	api   *investAPI
}

// NewSDKClient creates a broker client for the given token and account kind.
func NewSDKClient(token string, kind trading.AccountKind) *SDKClient {
	return &SDKClient{
		token: token,
		kind:  kind,
		api:   newInvestAPI(token, endpointForKind(kind)),
	}
}

func (c *SDKClient) configured() error {
	if c.token == "" {
		return fmt.Errorf("trading token not configured")
	}
	return nil
}

func (c *SDKClient) connect(ctx context.Context) (*investgo.Client, error) {
	if err := c.configured(); err != nil {
		return nil, err
	}
	client, err := c.api.connect(ctx)
	if err != nil {
		return nil, tradingErrorf("%v", err)
	}
	return client, nil
}

func endpointForKind(kind trading.AccountKind) string {
	if kind == trading.AccountKindSandbox {
		return sandboxEndpoint
	}
	return productionEndpoint
}

func isSandbox(kind trading.AccountKind) bool {
	return kind == trading.AccountKindSandbox
}

type sdkLogger struct {
	l *slog.Logger
}

func (s sdkLogger) Infof(template string, args ...any) {
	if s.l != nil {
		s.l.Info(fmt.Sprintf(template, args...))
	}
}

func (s sdkLogger) Errorf(template string, args ...any) {
	if s.l != nil {
		s.l.Error(fmt.Sprintf(template, args...))
	}
}

func (s sdkLogger) Fatalf(template string, args ...any) {
	if s.l != nil {
		s.l.Error(fmt.Sprintf(template, args...))
	}
}

func nowISO() string {
	return time.Now().UTC().Format(time.RFC3339)
}
