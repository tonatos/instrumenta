package moex

import (
	"encoding/json"
	"os"
	"strings"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/paths"
)

// DefaultFlags describes MOEX default status for one ISIN.
type DefaultFlags struct {
	HasDefault          bool
	HasTechnicalDefault bool
}

// DefaultsLoader loads bond default flags by ISIN.
type DefaultsLoader struct {
	path string
}

// NewDefaultsLoader creates a loader for vendored defaults.json.
func NewDefaultsLoader() *DefaultsLoader {
	return &DefaultsLoader{path: paths.DefaultsJSONPath()}
}

// NewDefaultsLoaderWithPath creates a loader for tests.
func NewDefaultsLoaderWithPath(path string) *DefaultsLoader {
	return &DefaultsLoader{path: path}
}

func (l *DefaultsLoader) Load() (map[string]DefaultFlags, error) {
	data, err := os.ReadFile(l.path)
	if err != nil {
		return map[string]DefaultFlags{}, nil
	}
	var payload struct {
		ISINFlags map[string]struct {
			HasDefault          bool `json:"has_default"`
			HasTechnicalDefault bool `json:"has_technical_default"`
		} `json:"isin_flags"`
	}
	if err := json.Unmarshal(data, &payload); err != nil {
		return nil, err
	}
	out := make(map[string]DefaultFlags, len(payload.ISINFlags))
	for isin, flags := range payload.ISINFlags {
		key := strings.ToUpper(strings.TrimSpace(isin))
		if key == "" || strings.HasPrefix(key, "_") {
			continue
		}
		out[key] = DefaultFlags{
			HasDefault:          flags.HasDefault,
			HasTechnicalDefault: flags.HasTechnicalDefault,
		}
	}
	return out, nil
}

// Apply sets HasDefault / HasTechnicalDefault on bonds from the registry.
func (l *DefaultsLoader) Apply(bs []bonds.BondRecord) []bonds.BondRecord {
	flags, err := l.Load()
	if err != nil || len(flags) == 0 {
		return bs
	}
	for i := range bs {
		if f, ok := flags[strings.ToUpper(bs[i].ISIN)]; ok {
			bs[i].HasDefault = f.HasDefault
			bs[i].HasTechnicalDefault = f.HasTechnicalDefault
		}
	}
	return bs
}
