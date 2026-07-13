package notifications

import (
	"database/sql"
	"encoding/json"
	"os"
	"path/filepath"
	"time"

	_ "modernc.org/sqlite"

	"github.com/tonatos/bond-monitor/backend/internal/domain/notifications"
)

// LedgerRepository is the SQLite outbox for notifier delivery guarantees.
type LedgerRepository struct {
	dbPath string
}

func NewLedgerRepository(dbPath string) *LedgerRepository {
	_ = os.MkdirAll(filepath.Dir(dbPath), 0o755)
	repo := &LedgerRepository{dbPath: dbPath}
	repo.initSchema()
	return repo
}

func (r *LedgerRepository) connect() (*sql.DB, error) {
	db, err := sql.Open("sqlite", r.dbPath)
	if err != nil {
		return nil, err
	}
	_, _ = db.Exec(`PRAGMA journal_mode=WAL`)
	return db, nil
}

func (r *LedgerRepository) initSchema() {
	db, err := r.connect()
	if err != nil {
		return
	}
	defer db.Close()
	_, _ = db.Exec(`
		CREATE TABLE IF NOT EXISTS delivery_ledger (
			fingerprint TEXT PRIMARY KEY,
			alert_kind TEXT NOT NULL,
			payload_json TEXT NOT NULL,
			bus_published_at TEXT,
			telegram_sent_at TEXT,
			last_attempt_at TEXT,
			retry_count INTEGER NOT NULL DEFAULT 0,
			created_at TEXT NOT NULL
		)
	`)
}

func (r *LedgerRepository) EnsureDetected(fingerprint string, alert notifications.Alert) (bool, error) {
	db, err := r.connect()
	if err != nil {
		return false, err
	}
	defer db.Close()
	payload, _ := json.Marshal(alertToPayload(alert))
	now := time.Now().UTC().Format(time.RFC3339)
	res, err := db.Exec(`
		INSERT OR IGNORE INTO delivery_ledger (fingerprint, alert_kind, payload_json, created_at)
		VALUES (?, ?, ?, ?)
	`, fingerprint, string(alert.Kind), string(payload), now)
	if err != nil {
		return false, err
	}
	n, _ := res.RowsAffected()
	return n == 1, nil
}

func (r *LedgerRepository) Get(fingerprint string) (*notifications.LedgerEntry, error) {
	db, err := r.connect()
	if err != nil {
		return nil, err
	}
	defer db.Close()
	row := db.QueryRow(`SELECT fingerprint, alert_kind, payload_json, bus_published_at, telegram_sent_at, last_attempt_at, retry_count FROM delivery_ledger WHERE fingerprint = ?`, fingerprint)
	return scanLedgerEntry(row)
}

func (r *LedgerRepository) Count() (int, error) {
	db, err := r.connect()
	if err != nil {
		return 0, err
	}
	defer db.Close()
	var c int
	err = db.QueryRow(`SELECT COUNT(*) FROM delivery_ledger`).Scan(&c)
	return c, err
}

func (r *LedgerRepository) DeleteAll() (int, error) {
	db, err := r.connect()
	if err != nil {
		return 0, err
	}
	defer db.Close()
	res, err := db.Exec(`DELETE FROM delivery_ledger`)
	if err != nil {
		return 0, err
	}
	n, _ := res.RowsAffected()
	return int(n), nil
}

func (r *LedgerRepository) DeleteForPortfolio(portfolioID string) (int, error) {
	db, err := r.connect()
	if err != nil {
		return 0, err
	}
	defer db.Close()
	rows, err := db.Query(`SELECT fingerprint, payload_json FROM delivery_ledger`)
	if err != nil {
		return 0, err
	}
	defer rows.Close()
	var toDelete []string
	for rows.Next() {
		var fp, payload string
		if err := rows.Scan(&fp, &payload); err != nil {
			return 0, err
		}
		if payloadPortfolioID(payload) == portfolioID {
			toDelete = append(toDelete, fp)
		}
	}
	if len(toDelete) == 0 {
		return 0, nil
	}
	for _, fp := range toDelete {
		if _, err := db.Exec(`DELETE FROM delivery_ledger WHERE fingerprint = ?`, fp); err != nil {
			return 0, err
		}
	}
	return len(toDelete), nil
}

func (r *LedgerRepository) MarkBusPublished(fingerprint string, at time.Time) (bool, error) {
	return r.markTimestamp(fingerprint, "bus_published_at", at)
}

func (r *LedgerRepository) MarkTelegramSent(fingerprint string, at time.Time) (bool, error) {
	db, err := r.connect()
	if err != nil {
		return false, err
	}
	defer db.Close()
	ts := at.UTC().Format(time.RFC3339)
	res, err := db.Exec(`
		UPDATE delivery_ledger SET telegram_sent_at = ?, last_attempt_at = ?, retry_count = retry_count + 1 WHERE fingerprint = ?
	`, ts, ts, fingerprint)
	if err != nil {
		return false, err
	}
	n, _ := res.RowsAffected()
	return n == 1, nil
}

func (r *LedgerRepository) ListPendingBus() ([]notifications.LedgerEntry, error) {
	return r.listWhere(`bus_published_at IS NULL`)
}

func (r *LedgerRepository) ListPendingTelegram() ([]notifications.LedgerEntry, error) {
	return r.listWhere(`telegram_sent_at IS NULL`)
}

func (r *LedgerRepository) markTimestamp(fingerprint, column string, at time.Time) (bool, error) {
	db, err := r.connect()
	if err != nil {
		return false, err
	}
	defer db.Close()
	ts := at.UTC().Format(time.RFC3339)
	res, err := db.Exec(`
		UPDATE delivery_ledger SET `+column+` = ?, last_attempt_at = ?, retry_count = retry_count + 1
		WHERE fingerprint = ? AND `+column+` IS NULL
	`, ts, ts, fingerprint)
	if err != nil {
		return false, err
	}
	n, _ := res.RowsAffected()
	return n == 1, nil
}

func (r *LedgerRepository) listWhere(where string) ([]notifications.LedgerEntry, error) {
	db, err := r.connect()
	if err != nil {
		return nil, err
	}
	defer db.Close()
	rows, err := db.Query(`SELECT fingerprint, alert_kind, payload_json, bus_published_at, telegram_sent_at, last_attempt_at, retry_count FROM delivery_ledger WHERE ` + where + ` ORDER BY created_at`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var result []notifications.LedgerEntry
	for rows.Next() {
		entry, err := scanLedgerEntry(rows)
		if err != nil {
			return nil, err
		}
		result = append(result, *entry)
	}
	return result, nil
}

type rowScanner interface {
	Scan(dest ...any) error
}

func scanLedgerEntry(row rowScanner) (*notifications.LedgerEntry, error) {
	var entry notifications.LedgerEntry
	var bus, tg, last sql.NullString
	if err := row.Scan(&entry.Fingerprint, &entry.AlertKind, &entry.PayloadJSON, &bus, &tg, &last, &entry.RetryCount); err != nil {
		return nil, err
	}
	entry.BusPublishedAt = parseDT(bus)
	entry.TelegramSentAt = parseDT(tg)
	entry.LastAttemptAt = parseDT(last)
	return &entry, nil
}

func parseDT(ns sql.NullString) *time.Time {
	if !ns.Valid || ns.String == "" {
		return nil
	}
	t, err := time.Parse(time.RFC3339, ns.String)
	if err != nil {
		return nil
	}
	return &t
}

func payloadPortfolioID(payloadJSON string) string {
	var payload map[string]any
	if err := json.Unmarshal([]byte(payloadJSON), &payload); err != nil {
		return ""
	}
	if id, ok := payload["portfolio_id"].(string); ok {
		return id
	}
	return ""
}

func alertToPayload(alert notifications.Alert) map[string]any {
	payload := map[string]any{
		"portfolio_id": alert.PortfolioID,
		"kind":         string(alert.Kind),
		"isin":         alert.ISIN,
		"name":         alert.Name,
		"reason":       alert.Reason,
		"urgency":      string(alert.Urgency),
	}
	if alert.FIGI != nil {
		payload["figi"] = *alert.FIGI
	}
	if alert.DueDate != nil {
		payload["due_date"] = alert.DueDate.Format("2006-01-02")
	}
	return payload
}

var _ notifications.LedgerRepository = (*LedgerRepository)(nil)
