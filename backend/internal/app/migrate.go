package app

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/persistence"
)

func runMigrations(ctx context.Context, db *persistence.DB) error {
	paths, err := migrationFiles()
	if err != nil {
		return err
	}
	for _, path := range paths {
		if err := applyMigrationFile(ctx, db, path); err != nil {
			return fmt.Errorf("%s: %w", filepath.Base(path), err)
		}
	}
	if err := persistence.EnsureMultiTenantSchema(ctx, db.DB); err != nil {
		return fmt.Errorf("ensure multi-tenant schema: %w", err)
	}
	if err := persistence.EnsureUsersNotifySchema(ctx, db.DB); err != nil {
		return fmt.Errorf("ensure users notify schema: %w", err)
	}
	if err := persistence.EnsureUsersTaxSchema(ctx, db.DB); err != nil {
		return fmt.Errorf("ensure users tax schema: %w", err)
	}
	return nil
}

func migrationFiles() ([]string, error) {
	if p := os.Getenv("BOND_MONITOR_MIGRATIONS"); p != "" {
		info, err := os.Stat(p)
		if err != nil {
			return nil, fmt.Errorf("stat migration path %s: %w", p, err)
		}
		if info.IsDir() {
			return listSQLMigrations(p)
		}
		return []string{p}, nil
	}
	dir := filepath.Join(repoRoot(), "backend", "migrations")
	return listSQLMigrations(dir)
}

func listSQLMigrations(dir string) ([]string, error) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil, fmt.Errorf("read migrations dir %s: %w", dir, err)
	}
	var paths []string
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".sql") {
			continue
		}
		paths = append(paths, filepath.Join(dir, entry.Name()))
	}
	sort.Strings(paths)
	if len(paths) == 0 {
		return nil, fmt.Errorf("no SQL migrations in %s", dir)
	}
	return paths, nil
}

func applyMigrationFile(ctx context.Context, db *persistence.DB, path string) error {
	raw, err := os.ReadFile(path)
	if err != nil {
		return fmt.Errorf("read migration: %w", err)
	}
	sql := extractGooseUp(string(raw))
	for _, stmt := range splitSQLStatements(sql) {
		if _, err := db.ExecContext(ctx, stmt); err != nil {
			return fmt.Errorf("migrate: %w", err)
		}
	}
	return nil
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
