package persistence

import (
	"context"
	"database/sql"
	"fmt"
	"path/filepath"
	"strings"

	"github.com/jmoiron/sqlx"
	_ "github.com/jackc/pgx/v5/stdlib"
	_ "modernc.org/sqlite"
)

// ParseDSN exposes DSN parsing for tests.
func ParseDSN(dsn string) (driver, normalized string) {
	return parseDSN(dsn)
}

// DB wraps sqlx.DB with driver metadata.
type DB struct {
	*sqlx.DB
	Driver string
}

// Open connects to SQLite or Postgres from a DSN.
// SQLite: "sqlite:///path/to.db" or "file:path?cache=shared&mode=rwc"
// Postgres: "postgres://..." or "postgresql://..."
func Open(dsn string) (*DB, error) {
	driver, normalized := parseDSN(dsn)
	db, err := sqlx.Connect(driver, normalized)
	if err != nil {
		return nil, fmt.Errorf("connect %s: %w", driver, err)
	}
	db.SetMaxOpenConns(10)
	return &DB{DB: db, Driver: driver}, nil
}

func parseDSN(dsn string) (driver, normalized string) {
	switch {
	case strings.HasPrefix(dsn, "sqlite:///"):
		path := strings.TrimPrefix(dsn, "sqlite:///")
		// sqlite:///Users/... loses the leading slash after trim.
		if path != "" && !filepath.IsAbs(path) && !strings.HasPrefix(path, ".") {
			path = "/" + path
		}
		if !filepath.IsAbs(path) {
			if abs, err := filepath.Abs(path); err == nil {
				path = abs
			}
		}
		return "sqlite", sqliteFileDSN(path)
	case strings.HasPrefix(dsn, "file:"):
		return "sqlite", dsn
	case strings.HasPrefix(dsn, "postgres://"), strings.HasPrefix(dsn, "postgresql://"):
		return "pgx", dsn
	default:
		if strings.Contains(dsn, "://") {
			return "sqlite", dsn
		}
		path := dsn
		if !filepath.IsAbs(path) {
			if abs, err := filepath.Abs(path); err == nil {
				path = abs
			}
		}
		return "sqlite", sqliteFileDSN(path)
	}
}

func sqliteFileDSN(path string) string {
	slash := filepath.ToSlash(path)
	if !strings.HasPrefix(slash, "/") {
		slash = "/" + slash
	}
	return "file:" + slash + "?cache=shared&mode=rwc"
}

// WithTx runs fn inside a transaction.
func (db *DB) WithTx(ctx context.Context, fn func(*sqlx.Tx) error) error {
	tx, err := db.BeginTxx(ctx, nil)
	if err != nil {
		return err
	}
	if err := fn(tx); err != nil {
		_ = tx.Rollback()
		return err
	}
	return tx.Commit()
}

// Ping verifies database connectivity.
func (db *DB) Ping(ctx context.Context) error {
	return db.DB.PingContext(ctx)
}

// Close closes the database.
func (db *DB) Close() error {
	return db.DB.Close()
}

// NullStringPtr converts sql.NullString to *string.
func NullStringPtr(ns sql.NullString) *string {
	if !ns.Valid {
		return nil
	}
	v := ns.String
	return &v
}

// StringPtr converts *string to sql.NullString.
func StringPtr(s *string) sql.NullString {
	if s == nil {
		return sql.NullString{}
	}
	return sql.NullString{String: *s, Valid: true}
}
