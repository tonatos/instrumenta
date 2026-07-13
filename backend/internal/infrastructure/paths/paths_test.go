package paths

import (
	"strings"
	"testing"
)

func TestRatingsJSONPathUsesRepoRootEnv(t *testing.T) {
	t.Setenv("BOND_MONITOR_REPO_ROOT", "/app")
	t.Setenv("BOND_MONITOR_ROOT", "")
	got := RatingsJSONPath()
	want := "/app/data/ratings.json"
	if got != want {
		t.Fatalf("got %q want %q", got, want)
	}
}

func TestRatingsJSONPathFallsBackToRepoRoot(t *testing.T) {
	t.Setenv("BOND_MONITOR_REPO_ROOT", "")
	t.Setenv("BOND_MONITOR_ROOT", "")
	got := RatingsJSONPath()
	if !strings.Contains(got, "data/ratings.json") {
		t.Fatalf("expected data/ratings.json in path, got %q", got)
	}
}
