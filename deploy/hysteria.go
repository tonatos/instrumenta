package main

import (
	"bytes"
	_ "embed"
	"fmt"
	"net/url"
	"strings"
	"text/template"
)

//go:embed templates/hysteria-client.yaml.tmpl
var hysteriaClientTemplate string

type hysteriaTemplateData struct {
	ServerURI string
}

// renderHysteriaClientYAML builds client config from inventory URI.
// Returns ok=false when hysteria is disabled (empty URI).
func renderHysteriaClientYAML(inv Inventory) (content string, ok bool, err error) {
	raw := strings.TrimSpace(inv.Hysteria2URI)
	if raw == "" {
		return "", false, nil
	}

	serverURI, err := normalizeHysteria2URI(raw)
	if err != nil {
		return "", false, err
	}

	tmpl, err := template.New("hysteria-client").Parse(hysteriaClientTemplate)
	if err != nil {
		return "", false, fmt.Errorf("parse hysteria template: %w", err)
	}
	var buf bytes.Buffer
	if err := tmpl.Execute(&buf, hysteriaTemplateData{ServerURI: serverURI}); err != nil {
		return "", false, fmt.Errorf("render hysteria template: %w", err)
	}
	return buf.String(), true, nil
}

func normalizeHysteria2URI(raw string) (string, error) {
	u, err := url.Parse(raw)
	if err != nil {
		return "", fmt.Errorf("hysteria2_uri: %w", err)
	}
	scheme := strings.ToLower(u.Scheme)
	if scheme != "hysteria2" && scheme != "hy2" {
		return "", fmt.Errorf("hysteria2_uri: unsupported scheme %q (want hysteria2)", u.Scheme)
	}
	if u.Host == "" {
		return "", fmt.Errorf("hysteria2_uri: missing host")
	}
	// Share-link fragments (#name) are not part of the protocol.
	u.Fragment = ""
	return u.String(), nil
}
