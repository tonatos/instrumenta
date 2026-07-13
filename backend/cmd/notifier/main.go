package main

import (
	"context"
	"log/slog"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/app"
	"github.com/tonatos/bond-monitor/backend/internal/interfaces/config"
	applogging "github.com/tonatos/bond-monitor/backend/internal/interfaces/logging"
)

func main() {
	settings := config.Load()
	logger := applogging.New(settings.LogLevel, settings.Debug)
	slog.SetDefault(logger)

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	scanner, _, cleanup, err := app.WireNotifier(ctx, settings, logger)
	if err != nil {
		logger.Error("wire notifier failed", "error", err)
		os.Exit(1)
	}
	defer cleanup()

	interval := settings.NotifierScanIntervalSec
	if interval < 60 {
		interval = 60
	}
	logger.Info("notifier started", "scan_interval_sec", interval)

	ticker := time.NewTicker(time.Duration(interval) * time.Second)
	defer ticker.Stop()

	runScan := func() {
		count, err := scanner.Run(ctx, time.Now())
		if err != nil {
			logger.Error("scan failed", "error", err)
			return
		}
		logger.Info("scan complete", "alerts_processed", count)
	}

	runScan()
	for {
		select {
		case <-ctx.Done():
			logger.Info("notifier stopped")
			return
		case <-ticker.C:
			runScan()
		}
	}
}
