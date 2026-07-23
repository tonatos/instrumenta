package persistence_test

import (
	"context"
	"testing"

	"github.com/tonatos/instrumenta/backend/internal/domain/trading"
	"github.com/tonatos/instrumenta/backend/internal/infrastructure/crypto"
	"github.com/tonatos/instrumenta/backend/internal/infrastructure/persistence"
)

func TestBrokerCredentials_tradeEnabledPersisted(t *testing.T) {
	db, err := persistence.Open("file:memdb_cred_trade?mode=memory&cache=shared")
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	if err := persistence.ApplyMigrations(db.DB, "sqlite", ""); err != nil {
		t.Fatal(err)
	}
	if err := persistence.EnsureBrokerCredentialsTradeSchema(context.Background(), db.DB); err != nil {
		t.Fatal(err)
	}
	kek, err := crypto.NewLocalKEK("test-cred-trade-kek-material!!!", 1)
	if err != nil {
		t.Fatal(err)
	}
	repo := persistence.NewBrokerCredentialsRepository(db, kek)
	ctx := context.Background()

	meta, err := repo.Put(ctx, 42, trading.AccountKindProduction, "t.readonly.token", false)
	if err != nil {
		t.Fatal(err)
	}
	if meta.TradeEnabled || !meta.TradeCapabilityChecked {
		t.Fatalf("meta=%+v", meta)
	}
	list, err := repo.ListMeta(ctx, 42)
	if err != nil || len(list) != 1 {
		t.Fatalf("list=%v err=%v", list, err)
	}
	if list[0].TradeEnabled || !list[0].TradeCapabilityChecked {
		t.Fatalf("list meta=%+v", list[0])
	}

	if err := repo.SetTradeCapability(ctx, 42, trading.AccountKindProduction, true); err != nil {
		t.Fatal(err)
	}
	list, err = repo.ListMeta(ctx, 42)
	if err != nil {
		t.Fatal(err)
	}
	if !list[0].TradeEnabled {
		t.Fatal("expected trade enabled after set")
	}
}
