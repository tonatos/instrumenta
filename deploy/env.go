package main

import (
	"bytes"
	_ "embed"
	"fmt"
	"strconv"
	"strings"
	"text/template"
)

//go:embed templates/env.prod.tmpl
var envProdTemplate string

type envTemplateData struct {
	Domain                   string
	ImageTag                 string
	TLSCaddyDataDir          string
	TLSCaddyConfigDir        string
	TinkoffToken             string
	TTradingTokenSandbox     string
	TTradingTokenProduction  string
	BrokerKEK                string
	KeyRate                  string
	TaxRate                  string
	MaxDays                  string
	MinVolumeRub             string
	LogLevel                 string
	AuthDisabled             string
	AuthSecret               string
	TelegramOIDCClientID     string
	TelegramOIDCClientSecret string
	DevTelegramID            string
	NotifierScanIntervalSec  string
	TelegramBotToken         string
	TelegramBotUsername      string
	YooKassaShopID           string
	YooKassaSecretKey        string
	ComplimentaryTelegramIDs string
}

func renderEnv(inv Inventory) (string, error) {
	inv.applyDefaults()
	tmpl, err := template.New("env.prod").Parse(envProdTemplate)
	if err != nil {
		return "", fmt.Errorf("parse env template: %w", err)
	}

	data := envTemplateData{
		Domain:                   inv.Domain,
		ImageTag:                 inv.ImageTag,
		TLSCaddyDataDir:          inv.TLSCaddyDataDir,
		TLSCaddyConfigDir:        inv.TLSCaddyConfigDir,
		TinkoffToken:             inv.TinkoffToken,
		TTradingTokenSandbox:     inv.TTradingTokenSandbox,
		TTradingTokenProduction:  inv.TTradingTokenProduction,
		BrokerKEK:                inv.BrokerKEK,
		KeyRate:                  formatFloat(inv.KeyRate),
		TaxRate:                  formatFloat(inv.TaxRate),
		MaxDays:                  strconv.Itoa(inv.MaxDays),
		MinVolumeRub:             strconv.Itoa(inv.MinVolumeRub),
		LogLevel:                 inv.LogLevel,
		AuthDisabled:             strconv.FormatBool(inv.AuthDisabled),
		AuthSecret:               inv.AuthSecret,
		TelegramOIDCClientID:     inv.TelegramOIDCClientID,
		TelegramOIDCClientSecret: inv.TelegramOIDCClientSecret,
		DevTelegramID:            strconv.FormatInt(inv.DevTelegramID, 10),
		NotifierScanIntervalSec:  strconv.Itoa(inv.NotifierScanIntervalSec),
		TelegramBotToken:         inv.TelegramBotToken,
		TelegramBotUsername:      inv.TelegramBotUsername,
		YooKassaShopID:           inv.YooKassaShopID,
		YooKassaSecretKey:        inv.YooKassaSecretKey,
		ComplimentaryTelegramIDs: inv.ComplimentaryTelegramIDs,
	}

	var buf bytes.Buffer
	if err := tmpl.Execute(&buf, data); err != nil {
		return "", fmt.Errorf("render env template: %w", err)
	}
	return buf.String(), nil
}

func formatFloat(value float64) string {
	s := strconv.FormatFloat(value, 'f', -1, 64)
	if strings.Contains(s, ".") {
		s = strings.TrimRight(strings.TrimRight(s, "0"), ".")
	}
	return s
}
