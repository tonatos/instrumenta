package main

import (
	"strings"
	"testing"
)

func TestRenderEnv(t *testing.T) {
	inv := Inventory{
		Domain:                  "bond.example.com",
		ImageTag:                "main",
		TLSCaddyDataDir:         "/opt/tls/caddy",
		TLSCaddyConfigDir:       "/opt/tls/caddy-config",
		TinkoffToken:            "t.test-token",
		TTradingTokenProduction: "t.prod-token",
		KeyRate:                 14.5,
		TaxRate:                 18,
		MaxDays:                 120,
		MinVolumeRub:            500000,
		LogLevel:                "INFO",
		AuthDisabled:            false,
		AuthSecret:              "secret-value",
		TelegramOIDCClientID:     "oidc-id",
		TelegramOIDCClientSecret: "oidc-secret",
		AllowedTelegramIDs:       "123,456",
		NotifierScanIntervalSec: 3600,
		TelegramBotToken:        "bot-token",
		TelegramNotifyUserID:    139693774,
	}

	out, err := renderEnv(inv)
	if err != nil {
		t.Fatalf("renderEnv: %v", err)
	}

	checks := []string{
		"DOMAIN=bond.example.com",
		"IMAGE_TAG=main",
		"TINKOFF_TOKEN=t.test-token",
		"T_TRADING_TOKEN_PRODUCTION=t.prod-token",
		"KEY_RATE=14.5",
		"TAX_RATE=18",
		"AUTH_DISABLED=false",
		"AUTH_SECRET=secret-value",
		"PUBLIC_APP_URL=https://bond.example.com",
		"TELEGRAM_BOT_TOKEN=bot-token",
		"ALLOWED_TELEGRAM_IDS=123,456",
		"NOTIFIER_SCAN_INTERVAL_SEC=3600",
	}
	for _, want := range checks {
		if !strings.Contains(out, want) {
			t.Fatalf("renderEnv missing %q\noutput:\n%s", want, out)
		}
	}
}
