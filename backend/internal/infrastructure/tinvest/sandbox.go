package tinvest

import (
	"context"

	"github.com/russianinvestments/invest-api-go-sdk/investgo"
	"github.com/tonatos/instrumenta/backend/internal/domain/shared"
)

func (c *SDKClient) OpenSandboxAccount(name string) (string, error) {
	if err := c.configured(); err != nil {
		return "", err
	}
	ctx := context.Background()
	client, err := c.connect(ctx)
	if err != nil {
		return "", err
	}
	resp, err := client.NewSandboxServiceClient().OpenSandboxAccount()
	if err != nil {
		return "", mapRPCError(err, "")
	}
	accountID := resp.GetAccountId()
	packageLogger.Info("sandbox account opened", "account_id", accountID, "name", name)
	return accountID, nil
}

func (c *SDKClient) CloseSandboxAccount(accountID string) error {
	if err := c.configured(); err != nil {
		return err
	}
	ctx := context.Background()
	client, err := c.connect(ctx)
	if err != nil {
		return err
	}
	_, err = client.NewSandboxServiceClient().CloseSandboxAccount(accountID)
	if err != nil {
		return mapRPCError(err, accountID)
	}
	packageLogger.Info("sandbox account closed", "account_id", accountID)
	return nil
}

func (c *SDKClient) SandboxPayIn(accountID string, amount shared.Rub) (shared.Rub, error) {
	if err := c.configured(); err != nil {
		return 0, err
	}
	ctx := context.Background()
	client, err := c.connect(ctx)
	if err != nil {
		return 0, err
	}
	units := int64(amount)
	nano := int32((float64(amount) - float64(units)) * 1_000_000_000)
	resp, err := client.NewSandboxServiceClient().SandboxPayIn(&investgo.SandboxPayInRequest{
		AccountId: accountID,
		Currency:  "RUB",
		Unit:      units,
		Nano:      nano,
	})
	if err != nil {
		return 0, mapRPCError(err, accountID)
	}
	balance := shared.Rub(0)
	if mv := resp.GetBalance(); mv != nil {
		balance = shared.Rub(mv.ToFloat())
	}
	packageLogger.Info("sandbox pay-in", "account_id", accountID, "amount", amount, "balance", balance)
	return balance, nil
}
