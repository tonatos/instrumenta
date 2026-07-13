package logging

import (
	"log"
	"log/slog"
	"os"
	"strings"
)

// New creates a slog logger from LOG_LEVEL / DEBUG settings.
func New(level string, debug bool) *slog.Logger {
	if debug {
		level = "DEBUG"
	}
	handler := slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{
		Level: parseLevel(level),
		ReplaceAttr: func(_ []string, attr slog.Attr) slog.Attr {
			if attr.Key == slog.TimeKey {
				attr.Value = slog.StringValue(attr.Value.Time().Format("2006-01-02 15:04:05"))
			}
			return attr
		},
	})
	return slog.New(handler)
}

// StdLogger bridges slog to the legacy *log.Logger interface.
func StdLogger(l *slog.Logger, prefix string) *log.Logger {
	if l == nil {
		return log.New(os.Stdout, prefix, log.LstdFlags|log.Lshortfile)
	}
	return log.New(&slogWriter{logger: l, prefix: prefix}, "", 0)
}

type slogWriter struct {
	logger *slog.Logger
	prefix string
}

func (w *slogWriter) Write(p []byte) (int, error) {
	msg := strings.TrimSpace(string(p))
	if w.prefix != "" {
		msg = strings.TrimSpace(strings.TrimPrefix(msg, w.prefix))
	}
	w.logger.Info(msg)
	return len(p), nil
}

func parseLevel(level string) slog.Level {
	switch strings.ToUpper(strings.TrimSpace(level)) {
	case "DEBUG":
		return slog.LevelDebug
	case "WARN", "WARNING":
		return slog.LevelWarn
	case "ERROR":
		return slog.LevelError
	default:
		return slog.LevelInfo
	}
}
