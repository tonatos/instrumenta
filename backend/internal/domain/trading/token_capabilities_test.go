package trading_test

import (
	"testing"

	"github.com/tonatos/instrumenta/backend/internal/domain/trading"
)

func TestAccountAllowsTrade_production(t *testing.T) {
	t.Parallel()
	cases := []struct {
		name  string
		level string
		want  bool
	}{
		{"full", trading.AccessLevelFullAccess, true},
		{"read_only", trading.AccessLevelReadOnly, false},
		{"no_access", trading.AccessLevelNoAccess, false},
		{"unspecified", trading.AccessLevelUnspecified, true},
		{"empty", "", true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()
			acc := trading.AccountInfo{
				ID: "a1", Kind: trading.AccountKindProduction, AccessLevel: tc.level,
			}
			if got := trading.AccountAllowsTrade(acc); got != tc.want {
				t.Fatalf("AccountAllowsTrade(%q)=%v want %v", tc.level, got, tc.want)
			}
		})
	}
}

func TestAccountAllowsTrade_sandbox(t *testing.T) {
	t.Parallel()
	cases := []struct {
		name  string
		level string
		want  bool
	}{
		{"unspecified", trading.AccessLevelUnspecified, true},
		{"empty", "", true},
		{"full", trading.AccessLevelFullAccess, true},
		{"read_only", trading.AccessLevelReadOnly, false},
		{"no_access", trading.AccessLevelNoAccess, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()
			acc := trading.AccountInfo{
				ID: "sb1", Kind: trading.AccountKindSandbox, AccessLevel: tc.level,
			}
			if got := trading.AccountAllowsTrade(acc); got != tc.want {
				t.Fatalf("AccountAllowsTrade(sandbox %q)=%v want %v", tc.level, got, tc.want)
			}
		})
	}
}

func TestTokenCanTrade(t *testing.T) {
	t.Parallel()
	if trading.TokenCanTrade(nil) {
		t.Fatal("empty list should not trade")
	}
	readOnly := []trading.AccountInfo{{
		ID: "a", Kind: trading.AccountKindProduction, AccessLevel: trading.AccessLevelReadOnly,
	}}
	if trading.TokenCanTrade(readOnly) {
		t.Fatal("all read-only should not trade")
	}
	mixed := []trading.AccountInfo{
		{ID: "a", Kind: trading.AccountKindProduction, AccessLevel: trading.AccessLevelReadOnly},
		{ID: "b", Kind: trading.AccountKindProduction, AccessLevel: trading.AccessLevelFullAccess},
	}
	if !trading.TokenCanTrade(mixed) {
		t.Fatal("one full-access should allow trade")
	}
}

func TestFindAccount(t *testing.T) {
	t.Parallel()
	accounts := []trading.AccountInfo{
		{ID: "a1", Name: "one"},
		{ID: "a2", Name: "two"},
	}
	if trading.FindAccount(accounts, "missing") != nil {
		t.Fatal("expected nil")
	}
	got := trading.FindAccount(accounts, "a2")
	if got == nil || got.Name != "two" {
		t.Fatalf("got %#v", got)
	}
}
