package app

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/persistence"
)

func runMigrations(ctx context.Context, db *persistence.DB) error {
	path := migrationPath()
	raw, err := os.ReadFile(path)
	if err != nil {
		return fmt.Errorf("read migration %s: %w", path, err)
	}
	sql := extractGooseUp(string(raw))
	for _, stmt := range splitSQLStatements(sql) {
		if _, err := db.ExecContext(ctx, stmt); err != nil {
			return fmt.Errorf("migrate: %w", err)
		}
	}
	return nil
}

func migrationPath() string {
	if p := os.Getenv("BOND_MONITOR_MIGRATIONS"); p != "" {
		return p
	}
	root := repoRoot()
	return filepath.Join(root, "backend", "migrations", "001_initial.sql")
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

func extractGooseUp(content string) string {
	const upMarker = "-- +goose Up"
	const downMarker = "-- +goose Down"
	start := strings.Index(content, upMarker)
	if start < 0 {
		return content
	}
	start += len(upMarker)
	end := strings.Index(content[start:], downMarker)
	if end < 0 {
		return strings.TrimSpace(content[start:])
	}
	return strings.TrimSpace(content[start : start+end])
}

func splitSQLStatements(sql string) []string {
	lines := strings.Split(sql, "\n")
	var cleaned []string
	for _, line := range lines {
		trimmed := strings.TrimSpace(line)
		if trimmed == "" || strings.HasPrefix(trimmed, "--") {
			continue
		}
		if strings.HasPrefix(trimmed, "-- +goose") {
			continue
		}
		cleaned = append(cleaned, line)
	}
	body := strings.Join(cleaned, "\n")
	parts := strings.Split(body, ";")
	var out []string
	for _, part := range parts {
		part = strings.TrimSpace(part)
		if part != "" {
			out = append(out, part)
		}
	}
	return out
}
