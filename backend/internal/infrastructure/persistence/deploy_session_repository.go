package persistence

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"time"

	"github.com/tonatos/instrumenta/backend/internal/domain/trading"
)

// DeploySessionRepository is the SQL implementation of trading.DeploySessionRepository.
type DeploySessionRepository struct {
	db *DB
}

func NewDeploySessionRepository(db *DB) *DeploySessionRepository {
	return &DeploySessionRepository{db: db}
}

type deploySessionItemJSON struct {
	ID                 string   `json:"id"`
	Kind               string   `json:"kind"`
	ISIN               string   `json:"isin"`
	Name               string   `json:"name"`
	Lots               int      `json:"lots"`
	FIGI               *string  `json:"figi"`
	SuggestedPricePct  float64  `json:"suggested_price_pct"`
	EstimatedAmountRub float64  `json:"estimated_amount_rub"`
	Reason             string   `json:"reason"`
	Status             string   `json:"status"`
	SourceISIN         *string  `json:"source_isin"`
	DueDate            *string  `json:"due_date"`
	OrderID            *string  `json:"order_id"`
	Urgency            string   `json:"urgency"`
}

func (r *DeploySessionRepository) expireStale(ctx context.Context, portfolioID string, now time.Time) error {
	_, err := r.db.ExecContext(ctx, `
		UPDATE deploy_sessions SET status = 'expired'
		WHERE portfolio_id = $1 AND status = 'active' AND expires_at <= $2
	`, portfolioID, now)
	return err
}

func (r *DeploySessionRepository) GetActive(ctx context.Context, portfolioID string) (*trading.DeploySession, error) {
	now := time.Now().UTC()
	if err := r.expireStale(ctx, portfolioID, now); err != nil {
		return nil, err
	}
	var row deploySessionRow
	err := r.db.GetContext(ctx, &row, `
		SELECT id, portfolio_id, status, cash_snapshot_rub, items_json, warnings_json, created_at, expires_at, completed_at
		FROM deploy_sessions
		WHERE portfolio_id = $1 AND status = 'active' AND expires_at > $2
		ORDER BY created_at DESC LIMIT 1
	`, portfolioID, now)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	s, err := deploySessionFromRow(row)
	if err != nil {
		return nil, err
	}
	return &s, nil
}

func (r *DeploySessionRepository) GetByID(ctx context.Context, sessionID string) (*trading.DeploySession, error) {
	var row deploySessionRow
	err := r.db.GetContext(ctx, &row, `
		SELECT id, portfolio_id, status, cash_snapshot_rub, items_json, warnings_json, created_at, expires_at, completed_at
		FROM deploy_sessions WHERE id = $1
	`, sessionID)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	s, err := deploySessionFromRow(row)
	if err != nil {
		return nil, err
	}
	return &s, nil
}

func (r *DeploySessionRepository) Save(ctx context.Context, session trading.DeploySession) (trading.DeploySession, error) {
	itemsJSON, err := json.Marshal(deploySessionItemsToJSON(session.Items))
	if err != nil {
		return trading.DeploySession{}, err
	}
	warningsJSON, err := json.Marshal(session.Warnings)
	if err != nil {
		return trading.DeploySession{}, err
	}
	row := deploySessionRow{
		ID: session.ID, PortfolioID: session.PortfolioID, Status: string(session.Status),
		CashSnapshotRub: session.CashSnapshotRub, ItemsJSON: string(itemsJSON), WarningsJSON: string(warningsJSON),
		CreatedAt: session.CreatedAt.UTC().Format(time.RFC3339),
		ExpiresAt: session.ExpiresAt.UTC().Format(time.RFC3339),
	}
	if session.CompletedAt != nil {
		row.CompletedAt = sql.NullString{String: session.CompletedAt.UTC().Format(time.RFC3339), Valid: true}
	}
	_, err = r.db.NamedExecContext(ctx, `
		INSERT INTO deploy_sessions (id, portfolio_id, status, cash_snapshot_rub, items_json, warnings_json, created_at, expires_at, completed_at)
		VALUES (:id, :portfolio_id, :status, :cash_snapshot_rub, :items_json, :warnings_json, :created_at, :expires_at, :completed_at)
		ON CONFLICT(id) DO UPDATE SET
			status = excluded.status, cash_snapshot_rub = excluded.cash_snapshot_rub,
			items_json = excluded.items_json, warnings_json = excluded.warnings_json,
			expires_at = excluded.expires_at, completed_at = excluded.completed_at
	`, row)
	if err != nil {
		return trading.DeploySession{}, err
	}
	return session, nil
}

func (r *DeploySessionRepository) HasActive(ctx context.Context, portfolioID string) (bool, error) {
	s, err := r.GetActive(ctx, portfolioID)
	return s != nil, err
}

func deploySessionFromRow(row deploySessionRow) (trading.DeploySession, error) {
	var items []deploySessionItemJSON
	if err := json.Unmarshal([]byte(row.ItemsJSON), &items); err != nil {
		return trading.DeploySession{}, err
	}
	var warnings []string
	if row.WarningsJSON != "" {
		if err := json.Unmarshal([]byte(row.WarningsJSON), &warnings); err != nil {
			return trading.DeploySession{}, err
		}
	}
	s := trading.DeploySession{
		ID: row.ID, PortfolioID: row.PortfolioID,
		Status: trading.DeploySessionStatus(row.Status),
		CashSnapshotRub: row.CashSnapshotRub, Warnings: warnings,
		CreatedAt: parseDBTime(row.CreatedAt), ExpiresAt: parseDBTime(row.ExpiresAt),
	}
	if row.CompletedAt.Valid {
		t := parseDBTime(row.CompletedAt.String)
		s.CompletedAt = &t
	}
	for _, item := range items {
		s.Items = append(s.Items, deploySessionItemFromJSON(item))
	}
	return s, nil
}

func deploySessionItemsToJSON(items []trading.DeploySessionItem) []deploySessionItemJSON {
	result := make([]deploySessionItemJSON, 0, len(items))
	for _, item := range items {
		j := deploySessionItemJSON{
			ID: item.ID, Kind: string(item.Kind), ISIN: item.ISIN, Name: item.Name,
			Lots: item.Lots, FIGI: item.FIGI, SuggestedPricePct: item.SuggestedPricePct,
			EstimatedAmountRub: item.EstimatedAmountRub, Reason: item.Reason,
			Status: string(item.Status), SourceISIN: item.SourceISIN, OrderID: item.OrderID,
			Urgency: string(item.Urgency),
		}
		if item.DueDate != nil {
			s := item.DueDate.Format("2006-01-02")
			j.DueDate = &s
		}
		result = append(result, j)
	}
	return result
}

func deploySessionItemFromJSON(j deploySessionItemJSON) trading.DeploySessionItem {
	item := trading.DeploySessionItem{
		ID: j.ID, Kind: trading.DeploySessionItemKind(j.Kind), ISIN: j.ISIN, Name: j.Name,
		Lots: j.Lots, FIGI: j.FIGI, SuggestedPricePct: j.SuggestedPricePct,
		EstimatedAmountRub: j.EstimatedAmountRub, Reason: j.Reason,
		Status: trading.DeploySessionItemStatus(j.Status), SourceISIN: j.SourceISIN,
		OrderID: j.OrderID, Urgency: trading.SuggestionUrgency(j.Urgency),
	}
	if j.DueDate != nil {
		t, _ := time.Parse("2006-01-02", *j.DueDate)
		item.DueDate = &t
	}
	return item
}
