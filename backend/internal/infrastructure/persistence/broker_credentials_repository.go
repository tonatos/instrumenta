package persistence

import (
	"context"
	"crypto/rand"
	"database/sql"
	"encoding/hex"
	"errors"
	"fmt"
	"sync"
	"time"

	"github.com/jmoiron/sqlx"
	"github.com/tonatos/instrumenta/backend/internal/domain/trading"
	"github.com/tonatos/instrumenta/backend/internal/infrastructure/crypto"
)

// BrokerCredentialMeta is non-secret credential metadata for UI.
type BrokerCredentialMeta struct {
	AccountKind             trading.AccountKind
	Fingerprint             string
	UpdatedAt               string
	TradeEnabled            bool
	TradeCapabilityChecked  bool
}

type brokerCredentialRow struct {
	ID                     string `db:"id"`
	OwnerTelegramID        int64  `db:"owner_telegram_id"`
	AccountKind            string `db:"account_kind"`
	Ciphertext             []byte `db:"ciphertext"`
	DEKWrapped             []byte `db:"dek_wrapped"`
	Nonce                  []byte `db:"nonce"`
	KEKVersion             int    `db:"kek_version"`
	Fingerprint            string `db:"fingerprint"`
	UpdatedAt              string `db:"updated_at"`
	TradeEnabled           int    `db:"trade_enabled"`
	TradeCapabilityChecked int    `db:"trade_capability_checked"`
}

// BrokerCredentialsRepository stores encrypted broker API tokens.
type BrokerCredentialsRepository struct {
	db      *DB
	wrapper crypto.KeyWrapper
	mu      sync.Mutex
	cache   map[string]cachedToken
}

type cachedToken struct {
	token     string
	expiresAt time.Time
}

func NewBrokerCredentialsRepository(db *DB, wrapper crypto.KeyWrapper) *BrokerCredentialsRepository {
	return &BrokerCredentialsRepository{
		db:      db,
		wrapper: wrapper,
		cache:   map[string]cachedToken{},
	}
}

// EnsureBrokerCredentialsTradeSchema adds trade capability columns idempotently.
func EnsureBrokerCredentialsTradeSchema(ctx context.Context, db *sqlx.DB) error {
	if err := ensureColumn(ctx, db, "broker_credentials", "trade_enabled", "INTEGER NOT NULL DEFAULT 0"); err != nil {
		return fmt.Errorf("broker_credentials.trade_enabled: %w", err)
	}
	if err := ensureColumn(ctx, db, "broker_credentials", "trade_capability_checked", "INTEGER NOT NULL DEFAULT 0"); err != nil {
		return fmt.Errorf("broker_credentials.trade_capability_checked: %w", err)
	}
	// One-shot: re-probe rows marked read-only after capability rule fix (UNSPECIFIED ≠ read-only).
	const resetKey = "broker_trade_cap_v2_reset"
	var exists int
	_ = db.GetContext(ctx, &exists, `SELECT COUNT(*) FROM app_settings WHERE key = $1`, resetKey)
	if exists == 0 {
		if _, err := db.ExecContext(ctx, `
			UPDATE broker_credentials SET trade_capability_checked = 0 WHERE trade_enabled = 0
		`); err != nil {
			return fmt.Errorf("reset trade capability for re-probe: %w", err)
		}
		if _, err := db.ExecContext(ctx, `
			INSERT INTO app_settings (key, value) VALUES ($1, '1')
			ON CONFLICT(key) DO NOTHING
		`, resetKey); err != nil {
			return fmt.Errorf("mark trade capability reset: %w", err)
		}
	}
	return nil
}

func (r *BrokerCredentialsRepository) ListMeta(ctx context.Context, ownerTelegramID int64) ([]BrokerCredentialMeta, error) {
	var rows []brokerCredentialRow
	err := r.db.SelectContext(ctx, &rows, `
		SELECT id, owner_telegram_id, account_kind, ciphertext, dek_wrapped, nonce, kek_version, fingerprint, updated_at,
			COALESCE(trade_enabled, 0) AS trade_enabled,
			COALESCE(trade_capability_checked, 0) AS trade_capability_checked
		FROM broker_credentials WHERE owner_telegram_id = $1
	`, ownerTelegramID)
	if err != nil {
		return nil, err
	}
	out := make([]BrokerCredentialMeta, 0, len(rows))
	for _, row := range rows {
		out = append(out, metaFromRow(row))
	}
	return out, nil
}

func (r *BrokerCredentialsRepository) Put(ctx context.Context, ownerTelegramID int64, kind trading.AccountKind, token string, tradeEnabled bool) (BrokerCredentialMeta, error) {
	id := newCredentialID()
	existing, _ := r.getRow(ctx, ownerTelegramID, kind)
	if existing != nil {
		id = existing.ID
	}
	aad := crypto.CredentialAAD(ownerTelegramID, id, string(kind))
	env, err := crypto.Encrypt(r.wrapper, []byte(token), aad)
	if err != nil {
		return BrokerCredentialMeta{}, err
	}
	fp := crypto.Fingerprint(token)
	now := time.Now().UTC().Format(time.RFC3339)
	tradeFlag := 0
	if tradeEnabled {
		tradeFlag = 1
	}
	_, err = r.db.ExecContext(ctx, `
		INSERT INTO broker_credentials (
			id, owner_telegram_id, account_kind, ciphertext, dek_wrapped, nonce, kek_version, fingerprint, updated_at,
			trade_enabled, trade_capability_checked
		)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 1)
		ON CONFLICT(owner_telegram_id, account_kind) DO UPDATE SET
			ciphertext = excluded.ciphertext,
			dek_wrapped = excluded.dek_wrapped,
			nonce = excluded.nonce,
			kek_version = excluded.kek_version,
			fingerprint = excluded.fingerprint,
			updated_at = excluded.updated_at,
			trade_enabled = excluded.trade_enabled,
			trade_capability_checked = 1
	`, id, ownerTelegramID, string(kind), env.Ciphertext, env.DEKWrapped, []byte{}, env.KEKVersion, fp, now, tradeFlag)
	if err != nil {
		return BrokerCredentialMeta{}, err
	}
	r.invalidate(ownerTelegramID, kind)
	return BrokerCredentialMeta{
		AccountKind:            kind,
		Fingerprint:            fp,
		UpdatedAt:              now,
		TradeEnabled:           tradeEnabled,
		TradeCapabilityChecked: true,
	}, nil
}

// SetTradeCapability stores probed trade rights without rotating the token.
func (r *BrokerCredentialsRepository) SetTradeCapability(ctx context.Context, ownerTelegramID int64, kind trading.AccountKind, tradeEnabled bool) error {
	tradeFlag := 0
	if tradeEnabled {
		tradeFlag = 1
	}
	res, err := r.db.ExecContext(ctx, `
		UPDATE broker_credentials
		SET trade_enabled = $1, trade_capability_checked = 1
		WHERE owner_telegram_id = $2 AND account_kind = $3
	`, tradeFlag, ownerTelegramID, string(kind))
	if err != nil {
		return err
	}
	n, _ := res.RowsAffected()
	if n == 0 {
		return ErrBrokerCredentialMissing
	}
	return nil
}

func (r *BrokerCredentialsRepository) Delete(ctx context.Context, ownerTelegramID int64, kind trading.AccountKind) (bool, error) {
	res, err := r.db.ExecContext(ctx, `
		DELETE FROM broker_credentials WHERE owner_telegram_id = $1 AND account_kind = $2
	`, ownerTelegramID, string(kind))
	if err != nil {
		return false, err
	}
	r.invalidate(ownerTelegramID, kind)
	n, _ := res.RowsAffected()
	return n > 0, nil
}

func (r *BrokerCredentialsRepository) GetPlaintext(ctx context.Context, ownerTelegramID int64, kind trading.AccountKind) (string, error) {
	cacheKey := cacheKey(ownerTelegramID, kind)
	r.mu.Lock()
	if c, ok := r.cache[cacheKey]; ok && time.Now().Before(c.expiresAt) {
		token := c.token
		r.mu.Unlock()
		return token, nil
	}
	r.mu.Unlock()

	row, err := r.getRow(ctx, ownerTelegramID, kind)
	if err != nil {
		return "", err
	}
	if row == nil {
		return "", ErrBrokerCredentialMissing
	}
	aad := crypto.CredentialAAD(ownerTelegramID, row.ID, row.AccountKind)
	plain, err := crypto.Decrypt(r.wrapper, crypto.Envelope{
		Ciphertext: row.Ciphertext,
		DEKWrapped: row.DEKWrapped,
		KEKVersion: row.KEKVersion,
	}, aad)
	if err != nil {
		return "", err
	}
	token := string(plain)
	r.mu.Lock()
	r.cache[cacheKey] = cachedToken{token: token, expiresAt: time.Now().Add(2 * time.Minute)}
	r.mu.Unlock()
	return token, nil
}

func (r *BrokerCredentialsRepository) getRow(ctx context.Context, ownerTelegramID int64, kind trading.AccountKind) (*brokerCredentialRow, error) {
	var row brokerCredentialRow
	err := r.db.GetContext(ctx, &row, `
		SELECT id, owner_telegram_id, account_kind, ciphertext, dek_wrapped, nonce, kek_version, fingerprint, updated_at,
			COALESCE(trade_enabled, 0) AS trade_enabled,
			COALESCE(trade_capability_checked, 0) AS trade_capability_checked
		FROM broker_credentials WHERE owner_telegram_id = $1 AND account_kind = $2
	`, ownerTelegramID, string(kind))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &row, nil
}

func metaFromRow(row brokerCredentialRow) BrokerCredentialMeta {
	return BrokerCredentialMeta{
		AccountKind:            trading.AccountKind(row.AccountKind),
		Fingerprint:            row.Fingerprint,
		UpdatedAt:              row.UpdatedAt,
		TradeEnabled:           row.TradeEnabled != 0,
		TradeCapabilityChecked: row.TradeCapabilityChecked != 0,
	}
}

func (r *BrokerCredentialsRepository) invalidate(ownerTelegramID int64, kind trading.AccountKind) {
	r.mu.Lock()
	delete(r.cache, cacheKey(ownerTelegramID, kind))
	r.mu.Unlock()
}

func cacheKey(ownerTelegramID int64, kind trading.AccountKind) string {
	return fmt.Sprintf("%d:%s", ownerTelegramID, kind)
}

func newCredentialID() string {
	var b [16]byte
	_, _ = rand.Read(b[:])
	return hex.EncodeToString(b[:])
}

// ErrBrokerCredentialMissing is returned when the user has no token for kind.
var ErrBrokerCredentialMissing = errors.New("broker credentials required")
