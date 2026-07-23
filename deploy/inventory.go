package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"gopkg.in/yaml.v3"
)

const defaultInventoryPath = "inventory.yaml"

// Inventory holds VPS connection settings and production secrets for bootstrap.
type Inventory struct {
	Host    string `yaml:"host"`
	SSHUser string `yaml:"ssh_user"`
	SSHKey  string `yaml:"ssh_key"`

	Domain   string `yaml:"domain"`
	AppDir   string `yaml:"app_dir"`
	GitRepo  string `yaml:"git_repo"`
	GitBranch string `yaml:"git_branch"`

	ProjectName  string   `yaml:"project_name"`
	ComposeFiles []string `yaml:"compose_files"`
	ImageTag     string   `yaml:"image_tag"`

	TLSCaddyDataDir   string `yaml:"tls_caddy_data_dir"`
	TLSCaddyConfigDir string `yaml:"tls_caddy_config_dir"`

	TinkoffToken            string  `yaml:"tinkoff_token"`
	// TTradingToken* are AUTH_DISABLED / emergency fallback only; prod users use /account.
	TTradingTokenSandbox    string  `yaml:"t_trading_token_sandbox"`
	TTradingTokenProduction string  `yaml:"t_trading_token_production"`
	BrokerKEK               string  `yaml:"broker_kek"`
	MaxDays                 int     `yaml:"max_days"`
	MinVolumeRub            int     `yaml:"min_volume_rub"`
	LogLevel                string  `yaml:"log_level"`

	AuthDisabled             bool   `yaml:"auth_disabled"`
	AuthSecret               string `yaml:"auth_secret"`
	TelegramOIDCClientID     string `yaml:"telegram_oidc_client_id"`
	TelegramOIDCClientSecret string `yaml:"telegram_oidc_client_secret"`
	DevTelegramID            int64  `yaml:"dev_telegram_id"`

	NotifierScanIntervalSec int    `yaml:"notifier_scan_interval_sec"`
	TelegramBotToken        string `yaml:"telegram_bot_token"`
	TelegramBotUsername     string `yaml:"telegram_bot_username"`

	YooKassaShopID           string `yaml:"yookassa_shop_id"`
	YooKassaSecretKey        string `yaml:"yookassa_secret_key"`
	ComplimentaryTelegramIDs string `yaml:"complimentary_telegram_ids"`

	GHCRUsername string `yaml:"ghcr_username"`
	GHCRToken    string `yaml:"ghcr_token"`
}

func LoadInventory(path string) (Inventory, error) {
	if path == "" {
		path = defaultInventoryPath
	}

	data, err := os.ReadFile(path)
	if err != nil {
		return Inventory{}, fmt.Errorf("read inventory %s: %w", path, err)
	}

	var inv Inventory
	if err := yaml.Unmarshal(data, &inv); err != nil {
		return Inventory{}, fmt.Errorf("parse inventory %s: %w", path, err)
	}

	inv.applyDefaults()
	if err := inv.validate(); err != nil {
		return Inventory{}, err
	}

	key, err := expandHome(inv.SSHKey)
	if err != nil {
		return Inventory{}, err
	}
	inv.SSHKey = key

	return inv, nil
}

func (inv *Inventory) applyDefaults() {
	if inv.SSHUser == "" {
		inv.SSHUser = "root"
	}
	if inv.SSHKey == "" {
		inv.SSHKey = "~/.ssh/id_ed25519"
	}
	if inv.AppDir == "" {
		inv.AppDir = "/opt/bond-monitor"
	}
	if inv.ProjectName == "" {
		inv.ProjectName = "bond-monitor"
	}
	if len(inv.ComposeFiles) == 0 {
		inv.ComposeFiles = []string{"docker-compose.yml", "docker-compose.prod.yml"}
	}
	if inv.GitRepo == "" {
		inv.GitRepo = "git@github.com:tonatos/bond-monitor.git"
	}
	if inv.GitBranch == "" {
		inv.GitBranch = "main"
	}
	if inv.ImageTag == "" {
		inv.ImageTag = "main"
	}
	if inv.TLSCaddyDataDir == "" {
		inv.TLSCaddyDataDir = "/opt/tls/caddy"
	}
	if inv.TLSCaddyConfigDir == "" {
		inv.TLSCaddyConfigDir = "/opt/tls/caddy-config"
	}
	if inv.MaxDays == 0 {
		inv.MaxDays = 120
	}
	if inv.MinVolumeRub == 0 {
		inv.MinVolumeRub = 500_000
	}
	if inv.LogLevel == "" {
		inv.LogLevel = "INFO"
	}
	if inv.NotifierScanIntervalSec == 0 {
		inv.NotifierScanIntervalSec = 3600
	}
	if inv.DevTelegramID == 0 {
		inv.DevTelegramID = 1
	}
}

func (inv Inventory) validate() error {
	switch {
	case strings.TrimSpace(inv.Host) == "":
		return fmt.Errorf("inventory: host is required")
	case strings.TrimSpace(inv.Domain) == "":
		return fmt.Errorf("inventory: domain is required")
	case !inv.AuthDisabled && strings.TrimSpace(inv.BrokerKEK) == "":
		return fmt.Errorf("inventory: broker_kek is required when auth_disabled is false")
	default:
		return nil
	}
}

func (inv Inventory) composeFilesFlag() string {
	parts := make([]string, 0, len(inv.ComposeFiles))
	for _, name := range inv.ComposeFiles {
		parts = append(parts, "-f "+shellQuote(name))
	}
	return strings.Join(parts, " ")
}

func expandHome(path string) (string, error) {
	if !strings.HasPrefix(path, "~/") {
		return path, nil
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return "", fmt.Errorf("expand ssh key path: %w", err)
	}
	return filepath.Join(home, strings.TrimPrefix(path, "~/")), nil
}

func shellQuote(value string) string {
	if value == "" {
		return "''"
	}
	return "'" + strings.ReplaceAll(value, "'", "'\"'\"'") + "'"
}
