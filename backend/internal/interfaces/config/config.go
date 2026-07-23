package config

import (
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/joho/godotenv"
)

// Settings mirrors backend/src/bond_monitor/interfaces/config.py.
type Settings struct {
	Host string
	Port int

	Debug    bool
	LogLevel string
	CORSOrigins []string

	DatabaseURL string

	CacheDir        string
	RatingsJSONPath string

	AuthDisabled bool
	AuthSecret   string
	PublicAppURL string

	DevTelegramID int64
	BrokerKEK     string

	TelegramOIDCClientID     string
	TelegramOIDCClientSecret string
	TelegramOIDCRedirectURI  string

	TinkoffToken            string
	TTradingTokenSandbox    string
	TTradingTokenProduction string

	KeyRate         float64
	TaxRate         float64
	MaxDays         int
	MinVolumeRub    float64
	BondCacheTTLSec float64

	RedisURL                 string
	NotifierScanIntervalSec  int
	TelegramBotToken         string
	TelegramBotUsername      string // optional override; otherwise resolved via getMe
	NotifierLedgerPath       string
	NotificationsDev         bool

	YooKassaShopID     string
	YooKassaSecretKey  string
	YooKassaReturnURL  string
	ComplimentaryTelegramIDs []int64
}

func repoRoot() string {
	if v := os.Getenv("BOND_MONITOR_REPO_ROOT"); v != "" {
		return v
	}
	wd, err := os.Getwd()
	if err != nil {
		return "."
	}
	dir := wd
	for {
		if _, err := os.Stat(filepath.Join(dir, "backend", "go.mod")); err == nil {
			return dir
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			break
		}
		dir = parent
	}
	return wd
}

func defaultDatabaseURL(root string) string {
	return "sqlite://" + filepath.Join(root, "cache", "bond_monitor.db")
}

func defaultNotifierLedgerPath(root string) string {
	return filepath.Join(root, "cache", "notifier_ledger.db")
}

// Load reads settings from environment variables.
func Load() Settings {
	root := repoRoot()
	_ = godotenv.Load(filepath.Join(root, ".env"))
	s := Settings{
		Host:     envString("HOST", "0.0.0.0"),
		Port:     envInt("PORT", 8000),
		Debug:    envBool("DEBUG", false),
		LogLevel: envString("LOG_LEVEL", "DEBUG"),
		CORSOrigins: envStringSlice("CORS_ORIGINS", []string{
			"http://localhost:3000",
			"http://localhost:5173",
		}),

		DatabaseURL: envString("DATABASE_URL", defaultDatabaseURL(root)),

		CacheDir:        filepath.Join(root, "cache"),
		RatingsJSONPath: filepath.Join(root, "data", "ratings.json"),

		AuthDisabled: envBool("AUTH_DISABLED", false),
		AuthSecret:   strings.TrimSpace(os.Getenv("AUTH_SECRET")),
		PublicAppURL: strings.TrimSpace(envString("PUBLIC_APP_URL", "http://localhost:5173")),

		DevTelegramID: envInt64("DEV_TELEGRAM_ID", 1),
		BrokerKEK:     strings.TrimSpace(os.Getenv("BROKER_KEK")),

		TelegramOIDCClientID:     strings.TrimSpace(os.Getenv("TELEGRAM_OIDC_CLIENT_ID")),
		TelegramOIDCClientSecret: strings.TrimSpace(os.Getenv("TELEGRAM_OIDC_CLIENT_SECRET")),
		TelegramOIDCRedirectURI:  strings.TrimSpace(os.Getenv("TELEGRAM_OIDC_REDIRECT_URI")),

		TinkoffToken:            os.Getenv("TINKOFF_TOKEN"),
		TTradingTokenSandbox:    os.Getenv("T_TRADING_TOKEN_SANDBOX"),
		TTradingTokenProduction: os.Getenv("T_TRADING_TOKEN_PRODUCTION"),

		KeyRate:         envFloat("KEY_RATE", 14.5),
		TaxRate:         envFloat("TAX_RATE", 13.0),
		MaxDays:         envInt("MAX_DAYS", 120),
		MinVolumeRub:    envFloat("MIN_VOLUME_RUB", 500_000),
		BondCacheTTLSec: envFloat("BOND_CACHE_TTL_SEC", 120),

		RedisURL:                envString("REDIS_URL", "redis://localhost:6379/0"),
		NotifierScanIntervalSec: envInt("NOTIFIER_SCAN_INTERVAL_SEC", 3600),
		TelegramBotToken:        os.Getenv("TELEGRAM_BOT_TOKEN"),
		TelegramBotUsername:     strings.TrimPrefix(strings.TrimSpace(os.Getenv("TELEGRAM_BOT_USERNAME")), "@"),
		NotifierLedgerPath:      envString("NOTIFIER_LEDGER_PATH", defaultNotifierLedgerPath(root)),
		NotificationsDev:        envBool("NOTIFICATIONS_DEV", false),

		YooKassaShopID:           strings.TrimSpace(os.Getenv("YOOKASSA_SHOP_ID")),
		YooKassaSecretKey:        strings.TrimSpace(os.Getenv("YOOKASSA_SECRET_KEY")),
		YooKassaReturnURL:        strings.TrimSpace(os.Getenv("YOOKASSA_RETURN_URL")),
		// Empty = nobody complimentary. Prod default lives in deploy/inventory.go.
		ComplimentaryTelegramIDs: envInt64CSV("COMPLIMENTARY_TELEGRAM_IDS", nil),
	}
	return s
}

// YooKassaReturnURLResolved defaults to PUBLIC_APP_URL/account/plan?payment=return.
func (s Settings) YooKassaReturnURLResolved() string {
	if s.YooKassaReturnURL != "" {
		return s.YooKassaReturnURL
	}
	return strings.TrimRight(s.PublicAppURL, "/") + "/account/plan?payment=return"
}

func (s Settings) AuthEnabled() bool {
	return !s.AuthDisabled
}

func (s Settings) TelegramOIDCRedirectURIResolved() string {
	if s.TelegramOIDCRedirectURI != "" {
		return s.TelegramOIDCRedirectURI
	}
	return strings.TrimRight(s.PublicAppURL, "/") + "/api/v1/auth/telegram/callback"
}

func (s Settings) TelegramOIDCConfigured() bool {
	return s.TelegramOIDCClientID != "" &&
		s.TelegramOIDCClientSecret != "" &&
		s.TelegramOIDCRedirectURIResolved() != ""
}

func (s Settings) TaxRateFraction() float64 {
	return s.TaxRate / 100.0
}

func envString(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func envInt(key string, fallback int) int {
	v := os.Getenv(key)
	if v == "" {
		return fallback
	}
	n, err := strconv.Atoi(strings.TrimSpace(v))
	if err != nil {
		return fallback
	}
	return n
}

func envInt64(key string, fallback int64) int64 {
	v := os.Getenv(key)
	if v == "" {
		return fallback
	}
	n, err := strconv.ParseInt(strings.TrimSpace(v), 10, 64)
	if err != nil {
		return fallback
	}
	return n
}

func envFloat(key string, fallback float64) float64 {
	v := os.Getenv(key)
	if v == "" {
		return fallback
	}
	n, err := strconv.ParseFloat(strings.TrimSpace(v), 64)
	if err != nil {
		return fallback
	}
	return n
}

func envBool(key string, fallback bool) bool {
	v := os.Getenv(key)
	if v == "" {
		return fallback
	}
	switch strings.ToLower(strings.TrimSpace(v)) {
	case "1", "true", "yes", "on":
		return true
	case "0", "false", "no", "off":
		return false
	default:
		return fallback
	}
}

func envStringSlice(key string, fallback []string) []string {
	v := os.Getenv(key)
	if v == "" {
		return fallback
	}
	parts := strings.Split(v, ",")
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p != "" {
			out = append(out, p)
		}
	}
	if len(out) == 0 {
		return fallback
	}
	return out
}

func envInt64CSV(key string, fallback []int64) []int64 {
	v := os.Getenv(key)
	if strings.TrimSpace(v) == "" {
		return fallback
	}
	parts := strings.Split(v, ",")
	out := make([]int64, 0, len(parts))
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p == "" {
			continue
		}
		n, err := strconv.ParseInt(p, 10, 64)
		if err != nil {
			continue
		}
		out = append(out, n)
	}
	if len(out) == 0 {
		return fallback
	}
	return out
}
