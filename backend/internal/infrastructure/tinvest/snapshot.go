package tinvest

import (
	"context"

	pb "github.com/russianinvestments/invest-api-go-sdk/proto"
	"github.com/tonatos/bond-monitor/backend/internal/domain/trading"
)

func (c *SDKClient) ListAccounts(kind trading.AccountKind) ([]trading.AccountInfo, error) {
	if err := c.configured(); err != nil {
		return nil, err
	}
	ctx := context.Background()
	client, err := c.connect(ctx)
	if err != nil {
		return nil, err
	}

	var accounts []*pb.Account
	if isSandbox(kind) {
		resp, err := client.NewSandboxServiceClient().GetSandboxAccounts()
		if err != nil {
			return nil, mapRPCError(err, "")
		}
		accounts = resp.GetAccounts()
	} else {
		resp, err := client.NewUsersServiceClient().GetAccounts(nil)
		if err != nil {
			return nil, mapRPCError(err, "")
		}
		accounts = resp.GetAccounts()
	}

	result := make([]trading.AccountInfo, 0, len(accounts))
	for _, acc := range accounts {
		if acc.GetStatus() != pb.AccountStatus_ACCOUNT_STATUS_OPEN {
			continue
		}
		isWritable := acc.GetAccessLevel() == pb.AccessLevel_ACCOUNT_ACCESS_LEVEL_FULL_ACCESS
		result = append(result, trading.AccountInfo{
			ID:          acc.GetId(),
			Name:        acc.GetName(),
			Kind:        kind,
			AccessLevel: acc.GetAccessLevel().String(),
			Status:      acc.GetStatus().String(),
			IsWritable:  isWritable,
		})
	}
	return result, nil
}

func (c *SDKClient) GetAccountSnapshot(kind trading.AccountKind, accountID string) (trading.InfraAccountSnapshot, error) {
	if err := c.configured(); err != nil {
		return trading.InfraAccountSnapshot{}, err
	}
	ctx := context.Background()
	client, err := c.connect(ctx)
	if err != nil {
		return trading.InfraAccountSnapshot{}, err
	}

	portfolioResp, err := client.NewOperationsServiceClient().GetPortfolio(
		accountID,
		pb.PortfolioRequest_RUB,
	)
	if err != nil {
		return trading.InfraAccountSnapshot{}, mapRPCError(err, accountID)
	}
	moneyRub := portfolioMoneyRub(portfolioResp.PortfolioResponse)
	blockedMoneyRub := positionsBlockedRub(ctx, c, accountID)

	bondNominals := make(map[string]float64)
	for _, pos := range portfolioResp.GetPositions() {
		if pos.GetInstrumentType() != "bond" {
			continue
		}
		figi := pos.GetFigi()
		if figi == "" {
			continue
		}
		if _, ok := bondNominals[figi]; ok {
			continue
		}
		if nominal, err := c.fetchBondNominal(ctx, figi, pos.GetInstrumentUid()); err == nil && nominal > 0 {
			bondNominals[figi] = nominal
		}
	}

	bonds := make(map[string]trading.InfraBondPosition)
	var others []trading.InfraOtherInstrument
	for _, pos := range portfolioResp.GetPositions() {
		var nominal *float64
		if pos.GetInstrumentType() == "bond" {
			if v, ok := bondNominals[pos.GetFigi()]; ok {
				nominal = &v
			}
		}
		kindPos, bond, other := classifyPosition(pos, nominal)
		switch kindPos {
		case "bond":
			if bond != nil {
				bonds[bond.FIGI] = *bond
			}
		case "other":
			if other != nil {
				others = append(others, *other)
			}
		}
	}

	return trading.InfraAccountSnapshot{
		AccountID:        accountID,
		AccountKind:      kind,
		MoneyRub:         moneyRub,
		BlockedMoneyRub:  blockedMoneyRub,
		BondPositions:    bonds,
		OtherInstruments: others,
		FetchedAt:        nowISO(),
	}, nil
}
