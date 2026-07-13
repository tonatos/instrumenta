package ratings

import (
	"encoding/json"
	"log"
	"os"
	"path/filepath"
	"strings"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/paths"
)

// Loader loads vendored and auto-scraped credit ratings.
type Loader struct {
	vendoredPath string
	autoPath     string
}

// NewLoader creates a ratings loader.
func NewLoader() *Loader {
	cacheDir := paths.CacheDir()
	return &Loader{
		vendoredPath: paths.RatingsJSONPath(),
		autoPath:     filepath.Join(cacheDir, "ratings_auto.json"),
	}
}

func (l *Loader) LoadRatings() (map[string]any, error) {
	data, err := os.ReadFile(l.vendoredPath)
	if err != nil {
		log.Printf("ratings.json not found at %s", l.vendoredPath)
		return map[string]any{}, nil
	}
	var ratings map[string]any
	if err := json.Unmarshal(data, &ratings); err != nil {
		return map[string]any{}, err
	}
	return ratings, nil
}

func (l *Loader) LoadAutoRatings() (map[string]any, error) {
	data, err := os.ReadFile(l.autoPath)
	if err != nil {
		return nil, nil
	}
	var envelope map[string]any
	if err := json.Unmarshal(data, &envelope); err != nil {
		return nil, nil
	}
	if _, ok := envelope["isin_ratings"].(map[string]any); !ok {
		return nil, nil
	}
	return envelope, nil
}

func (l *Loader) ApplyRatings(bs []bonds.BondRecord, ratings map[string]any, autoRatings map[string]any) []bonds.BondRecord {
	autoISIN := map[string]string{}
	if autoRatings != nil {
		if m, ok := autoRatings["isin_ratings"].(map[string]any); ok {
			for isin, v := range m {
				if s, ok := v.(string); ok {
					autoISIN[isin] = s
				}
			}
		}
	}
	vendoredISIN := map[string]string{}
	vendoredNames := map[string]string{}
	if ratings != nil {
		if m, ok := ratings["isin_ratings"].(map[string]any); ok {
			for isin, v := range m {
				if s, ok := v.(string); ok {
					vendoredISIN[isin] = s
				}
			}
		}
		if m, ok := ratings["name_ratings"].(map[string]any); ok {
			for name, v := range m {
				if s, ok := v.(string); ok {
					vendoredNames[strings.ToLower(name)] = s
				}
			}
		}
	}
	for i := range bs {
		if rating, ok := autoISIN[bs[i].ISIN]; ok {
			bs[i].CreditRating = &rating
			continue
		}
		if rating, ok := vendoredISIN[bs[i].ISIN]; ok {
			bs[i].CreditRating = &rating
			continue
		}
		nameLower := strings.ToLower(bs[i].Name)
		for pattern, rating := range vendoredNames {
			if strings.Contains(nameLower, pattern) {
				r := rating
				bs[i].CreditRating = &r
				break
			}
		}
	}
	return bs
}

var _ bonds.RatingsLoader = (*Loader)(nil)
