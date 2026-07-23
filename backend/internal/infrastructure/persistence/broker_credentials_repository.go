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

	"github.com/tonatos/instrumenta/backend/internal/domain/trading"
	"github.com/tonatos/instrumenta/backend/internal/infrastructure/crypto"
)

// BrokerCredentialMeta is non-secret credential metadata for UI.
type BrokerCredentialMeta struct {
	AccountKind trading.AccountKind
	Fingerprint string
	UpdatedAt   string
}

type brokerCredentialRow struct {
	ID              string `db:"id"`
	OwnerTelegramID int64  `db:"owner_telegram_id"`
	AccountKind     string `db:"account_kind"`
	Ciphertext      []byte `db:"ciphertext"`
	DEKWrapped      []byte `db:"dek_wrapped"`
	Nonce           []byte `db:"nonce"`
	KEKVersion      int    `db:"kek_version"`
	Fingerprint     string `db:"fingerprint"`
	UpdatedAt       string `db:"updated_at"`
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

func (r *BrokerCredentialsRepository) ListMeta(ctx context.Context, ownerTelegramID int64) ([]BrokerCredentialMeta, error) {
	var rows []brokerCredentialRow
	err := r.db.SelectContext(ctx, &rows, `
		SELECT id, owner_telegram_id, account_kind, ciphertext, dek_wrapped, nonce, kek_version, fingerprint, updated_at
		FROM broker_credentials WHERE owner_telegram_id = $1
	`, ownerTelegramID)
	if err != nil {
		return nil, err
	}
	out := make([]BrokerCredentialMeta, 0, len(rows))
	for _, row := range rows {
		out = append(out, BrokerCredentialMeta{
			AccountKind: trading.AccountKind(row.AccountKind),
			Fingerprint: row.Fingerprint,
			UpdatedAt:   row.UpdatedAt,
		})
	}
	return out, nil
}

func (r *BrokerCredentialsRepository) Put(ctx context.Context, ownerTelegramID int64, kind trading.AccountKind, token string) (BrokerCredentialMeta, error) {
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
	_, err = r.db.ExecContext(ctx, `
		INSERT INTO broker_credentials (id, owner_telegram_id, account_kind, ciphertext, dek_wrapped, nonce, kek_version, fingerprint, updated_at)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
		ON CONFLICT(owner_telegram_id, account_kind) DO UPDATE SET
			ciphertext = excluded.ciphertext,
			dek_wrapped = excluded.dek_wrapped,
			nonce = excluded.nonce,
			kek_version = excluded.kek_version,
			fingerprint = excluded.fingerprint,
			updated_at = excluded.updated_at
	`, id, ownerTelegramID, string(kind), env.Ciphertext, env.DEKWrapped, []byte{}, env.KEKVersion, fp, now)
	if err != nil {
		return BrokerCredentialMeta{}, err
	}
	r.invalidate(ownerTelegramID, kind)
	return BrokerCredentialMeta{AccountKind: kind, Fingerprint: fp, UpdatedAt: now}, nil
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
		SELECT id, owner_telegram_id, account_kind, ciphertext, dek_wrapped, nonce, kek_version, fingerprint, updated_at
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
