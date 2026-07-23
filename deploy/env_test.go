package main

import (
	"strings"
	"testing"
)

func TestRenderEnv(t *testing.T) {
	inv := Inventory{
		Domain:                   "bond.example.com",
		ImageTag:                 "main",
		TLSCaddyDataDir:          "/opt/tls/caddy",
		TLSCaddyConfigDir:        "/opt/tls/caddy-config",
		TinkoffToken:             "t.test-token",
		TTradingTokenProduction:  "t.prod-token",
		BrokerKEK:                "test-broker-kek-material",
		MaxDays:                  120,
		MinVolumeRub:             500000,
		LogLevel:                 "INFO",
		AuthDisabled:             false,
		AuthSecret:               "secret-value",
		TelegramOIDCClientID:     "oidc-id",
		TelegramOIDCClientSecret: "oidc-secret",
		DevTelegramID:            1,
		NotifierScanIntervalSec:  3600,
		TelegramBotToken:         "bot-token",
		TelegramBotUsername:      "instrumenta_bot",
		ComplimentaryTelegramIDs: "111999777",
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
		"BROKER_KEK=test-broker-kek-material",
		"AUTH_DISABLED=false",
		"AUTH_SECRET=secret-value",
		"PUBLIC_APP_URL=https://bond.example.com",
		"TELEGRAM_BOT_TOKEN=bot-token",
		"TELEGRAM_BOT_USERNAME=instrumenta_bot",
		"DEV_TELEGRAM_ID=1",
		"NOTIFIER_SCAN_INTERVAL_SEC=3600",
		"COMPLIMENTARY_TELEGRAM_IDS=111999777",
	}
	for _, want := range checks {
		if !strings.Contains(out, want) {
			t.Fatalf("renderEnv missing %q\noutput:\n%s", want, out)
		}
	}
	if strings.Contains(out, "KEY_RATE=") {
		t.Fatal("KEY_RATE should be removed from prod env")
	}
	if strings.Contains(out, "TAX_RATE=") {
		t.Fatal("TAX_RATE should be removed from prod env")
	}
	if strings.Contains(out, "ALLOWED_TELEGRAM_IDS") {
		t.Fatal("ALLOWED_TELEGRAM_IDS should be removed from prod env")
	}
	if strings.Contains(out, "TELEGRAM_NOTIFY_USER_ID") {
		t.Fatal("TELEGRAM_NOTIFY_USER_ID should be removed from prod env")
	}
	if strings.Contains(out, "TENANT_BACKFILL_TELEGRAM_ID") {
		t.Fatal("TENANT_BACKFILL_TELEGRAM_ID should be removed from prod env")
	}
}

func TestValidateRequiresBrokerKEKWhenAuthEnabled(t *testing.T) {
	inv := Inventory{Host: "1.2.3.4", Domain: "example.com", AuthDisabled: false}
	if err := inv.validate(); err == nil {
		t.Fatal("expected broker_kek required")
	}
	inv.BrokerKEK = "kek"
	if err := inv.validate(); err != nil {
		t.Fatalf("unexpected: %v", err)
	}
	inv.AuthDisabled = true
	inv.BrokerKEK = ""
	if err := inv.validate(); err != nil {
		t.Fatalf("auth disabled should allow empty kek: %v", err)
	}
}
