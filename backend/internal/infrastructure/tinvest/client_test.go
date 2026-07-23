package tinvest

import (
	"strings"
	"testing"

	"github.com/tonatos/instrumenta/backend/internal/domain/trading"
)

func TestSDKClient_RequiresToken(t *testing.T) {
	c := NewSDKClient("", trading.AccountKindSandbox)
	_, err := c.GetAccountSnapshot(trading.AccountKindSandbox, "acc-1")
	if err == nil {
		t.Fatal("expected error without token")
	}
	if strings.Contains(err.Error(), "not yet wired") {
		t.Fatalf("SDK still stubbed: %v", err)
	}
}

func TestMakeRequestUID_UUIDFormat(t *testing.T) {
	uid := NewSDKClient("t", trading.AccountKindSandbox).MakeRequestUID(
		"acc", "figi", "BUY", 1, "key", "salt",
	)
	if len(uid) != 36 {
		t.Fatalf("expected UUID length 36, got %d: %q", len(uid), uid)
	}
	parts := strings.Split(uid, "-")
	if len(parts) != 5 || len(parts[0]) != 8 || len(parts[4]) != 12 {
		t.Fatalf("unexpected UUID format: %q", uid)
	}
}

func TestMakeRequestUID_Deterministic(t *testing.T) {
	c := NewSDKClient("t", trading.AccountKindSandbox)
	a := c.MakeRequestUID("acc", "figi", "BUY", 2, "k", "")
	b := c.MakeRequestUID("acc", "figi", "BUY", 2, "k", "")
	if a != b {
		t.Fatalf("expected deterministic UID, got %q vs %q", a, b)
	}
}
