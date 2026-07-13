package paths

import (
	"os"
	"path/filepath"
	"runtime"
)

func repoRoot() string {
	if v := os.Getenv("BOND_MONITOR_REPO_ROOT"); v != "" {
		return v
	}
	if root := os.Getenv("BOND_MONITOR_ROOT"); root != "" {
		return root
	}
	if wd, err := os.Getwd(); err == nil {
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
	}
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		return "."
	}
	// backend/internal/infrastructure/paths -> repo root
	return filepath.Clean(filepath.Join(filepath.Dir(file), "..", "..", "..", ".."))
}

// CacheDir returns cache directory (overridable via CACHE_DIR env).
func CacheDir() string {
	if dir := os.Getenv("CACHE_DIR"); dir != "" {
		return dir
	}
	return filepath.Join(repoRoot(), "cache")
}

// RatingsJSONPath returns path to vendored ratings.json.
func RatingsJSONPath() string {
	return filepath.Join(repoRoot(), "data", "ratings.json")
}
