package tinvest

import (
	"context"
	"fmt"
	"sync"

	"github.com/russianinvestments/invest-api-go-sdk/investgo"
)

type investAPI struct {
	token    string
	endpoint string
	mu       sync.Mutex
	client   *investgo.Client
}

func newInvestAPI(token, endpoint string) *investAPI {
	return &investAPI{token: token, endpoint: endpoint}
}

func (a *investAPI) connect(ctx context.Context) (*investgo.Client, error) {
	if a.token == "" {
		return nil, fmt.Errorf("T-Invest token not configured")
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.client != nil {
		return a.client, nil
	}
	caFile, err := tbankTLSCAFile()
	if err != nil {
		return nil, fmt.Errorf("T-Invest TLS CA: %w", err)
	}
	cfg := investgo.Config{
		Token:              a.token,
		EndPoint:           a.endpoint,
		AppName:            appName,
		TLSCACertFile:      caFile,
		InsecureSkipVerify: tbankTLSInsecureSkipVerify(),
	}
	client, err := investgo.NewClient(ctx, cfg, sdkLogger{packageLogger})
	if err != nil {
		return nil, fmt.Errorf("T-Invest connect: %w", err)
	}
	a.client = client
	packageLogger.Debug("tinvest client connected", "endpoint", a.endpoint)
	return client, nil
}
