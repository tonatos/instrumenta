package ratings

import (
	"strings"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
)

// NormalizeRating maps smart-lab / MOEX rating labels to internal ru-scale keys.
func NormalizeRating(raw string) (string, bool) {
	s := strings.TrimSpace(raw)
	if s == "" || s == "—" || strings.EqualFold(s, "нет") || strings.EqualFold(s, "n/a") {
		return "", false
	}
	if strings.HasPrefix(strings.ToLower(s), "ru") {
		if _, ok := bonds.RatingOrder[s]; ok {
			return s, true
		}
	}
	if _, ok := bonds.RatingOrder[s]; ok {
		return "ru" + s, true
	}
	return "", false
}
