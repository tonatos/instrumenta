package app

import "strings"

// NormalizeDSN converts Python-style SQLAlchemy URLs to Go persistence DSNs.
func NormalizeDSN(url string) string {
	url = strings.TrimSpace(url)
	switch {
	case strings.HasPrefix(url, "sqlite+aiosqlite:///"):
		return "sqlite://" + strings.TrimPrefix(url, "sqlite+aiosqlite:///")
	case strings.HasPrefix(url, "sqlite+aiosqlite://"):
		return "sqlite://" + strings.TrimPrefix(url, "sqlite+aiosqlite://")
	default:
		return url
	}
}

func maskDSN(dsn string) string {
	if dsn == "" {
		return ""
	}
	if strings.HasPrefix(dsn, "sqlite:") {
		return dsn
	}
	if at := strings.LastIndex(dsn, "@"); at >= 0 {
		return "***@" + dsn[at+1:]
	}
	return dsn
}
