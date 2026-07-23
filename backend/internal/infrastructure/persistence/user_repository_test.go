package persistence

import (
	"context"
	"path/filepath"
	"testing"
	"time"
)

func openUserTestDB(t *testing.T) *DB {
	t.Helper()
	dir := t.TempDir()
	db, err := Open("sqlite://" + filepath.Join(dir, "users.db"))
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	t.Cleanup(func() { _ = db.Close() })
	if err := ApplyMigrations(db.DB, "sqlite", ""); err != nil {
		t.Fatalf("migrate: %v", err)
	}
	if err := EnsureUsersNotifySchema(context.Background(), db.DB); err != nil {
		t.Fatalf("ensure notify schema: %v", err)
	}
	if err := EnsureUsersTaxSchema(context.Background(), db.DB); err != nil {
		t.Fatalf("ensure tax schema: %v", err)
	}
	return db
}

func TestUserRepository_BotConnectionOptIn(t *testing.T) {
	db := openUserTestDB(t)
	repo := NewUserRepository(db)
	ctx := context.Background()

	if err := repo.Upsert(ctx, 42, "Alice"); err != nil {
		t.Fatalf("upsert: %v", err)
	}
	connected, err := repo.IsBotConnected(ctx, 42)
	if err != nil {
		t.Fatalf("is connected: %v", err)
	}
	if connected {
		t.Fatal("expected not connected before /start")
	}

	at := time.Date(2026, 7, 23, 10, 0, 0, 0, time.UTC)
	if err := repo.MarkBotConnected(ctx, 42, "Alice", at); err != nil {
		t.Fatalf("mark connected: %v", err)
	}
	connected, err = repo.IsBotConnected(ctx, 42)
	if err != nil || !connected {
		t.Fatalf("expected connected, got %v err=%v", connected, err)
	}

	// Upsert must not clear opt-in.
	if err := repo.Upsert(ctx, 42, "Alice Updated"); err != nil {
		t.Fatalf("upsert again: %v", err)
	}
	connected, err = repo.IsBotConnected(ctx, 42)
	if err != nil || !connected {
		t.Fatalf("upsert cleared bot connection: connected=%v err=%v", connected, err)
	}

	if err := repo.MarkBotDisconnected(ctx, 42); err != nil {
		t.Fatalf("disconnect: %v", err)
	}
	connected, err = repo.IsBotConnected(ctx, 42)
	if err != nil || connected {
		t.Fatalf("expected disconnected, got %v err=%v", connected, err)
	}
}

func TestUserRepository_TaxRatePct(t *testing.T) {
	db := openUserTestDB(t)
	if err := EnsureUsersTaxSchema(context.Background(), db.DB); err != nil {
		t.Fatalf("ensure tax schema: %v", err)
	}
	repo := NewUserRepository(db)
	ctx := context.Background()

	pct, err := repo.TaxRatePct(ctx, 1)
	if err != nil || pct != 13 {
		t.Fatalf("default missing user: got %v err=%v", pct, err)
	}
	if err := repo.SetTaxRatePct(ctx, 1, 0); err != nil {
		t.Fatalf("set 0: %v", err)
	}
	pct, err = repo.TaxRatePct(ctx, 1)
	if err != nil || pct != 0 {
		t.Fatalf("got %v err=%v", pct, err)
	}
	if err := repo.SetTaxRatePct(ctx, 1, 22); err != nil {
		t.Fatalf("set 22: %v", err)
	}
	pct, err = repo.TaxRatePct(ctx, 1)
	if err != nil || pct != 22 {
		t.Fatalf("got %v err=%v", pct, err)
	}
	if err := repo.SetTaxRatePct(ctx, 1, 14); err == nil {
		t.Fatal("expected validation error")
	}
}

func TestUserRepository_MarkBotConnectedCreatesUser(t *testing.T) {
	db := openUserTestDB(t)
	repo := NewUserRepository(db)
	ctx := context.Background()

	at := time.Now().UTC()
	if err := repo.MarkBotConnected(ctx, 99, "Bob", at); err != nil {
		t.Fatalf("mark: %v", err)
	}
	connected, err := repo.IsBotConnected(ctx, 99)
	if err != nil || !connected {
		t.Fatalf("expected connected for new user, got %v err=%v", connected, err)
	}
}
