package persistence

import (
	"database/sql"
)

type portfolioRow struct {
	ID               string         `db:"id"`
	Name             string         `db:"name"`
	CreatedAt        string         `db:"created_at"`
	UpdatedAt        string         `db:"updated_at"`
	OwnerTelegramID  int64          `db:"owner_telegram_id"`
	InitialAmountRub float64        `db:"initial_amount_rub"`
	HorizonDate      string         `db:"horizon_date"`
	RiskProfile      string         `db:"risk_profile"`
	CashBalanceRub   float64        `db:"cash_balance_rub"`
	Mode             string         `db:"mode"`
	AccountID        sql.NullString `db:"account_id"`
	AccountKind      sql.NullString `db:"account_kind"`
	Data             string         `db:"data"`
}

type favoriteRow struct {
	ISIN    string `db:"isin"`
	AddedAt string `db:"added_at"`
}

type appSettingRow struct {
	Key   string `db:"key"`
	Value string `db:"value"`
}

type userNotificationRow struct {
	ID          string         `db:"id"`
	Fingerprint string         `db:"fingerprint"`
	PortfolioID string         `db:"portfolio_id"`
	Kind        string         `db:"kind"`
	PayloadJSON string         `db:"payload_json"`
	Urgency     string         `db:"urgency"`
	CreatedAt   string         `db:"created_at"`
	ReadAt      sql.NullString `db:"read_at"`
	DismissedAt sql.NullString `db:"dismissed_at"`
}

type deploySessionRow struct {
	ID              string         `db:"id"`
	PortfolioID     string         `db:"portfolio_id"`
	Status          string         `db:"status"`
	CashSnapshotRub float64        `db:"cash_snapshot_rub"`
	ItemsJSON       string         `db:"items_json"`
	WarningsJSON    string         `db:"warnings_json"`
	CreatedAt       string         `db:"created_at"`
	ExpiresAt       string         `db:"expires_at"`
	CompletedAt     sql.NullString `db:"completed_at"`
}
