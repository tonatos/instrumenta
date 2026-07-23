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

	scanner, billing, inbox, _, cleanup, err := app.WireNotifier(ctx, settings, logger)
	if err != nil {
		logger.Error("wire notifier failed", "error", err)
		os.Exit(1)
	}
	defer cleanup()

	if inbox != nil {
		go inbox.Run(ctx)
		logger.Info("telegram bot inbox started")
	}

	interval := settings.NotifierScanIntervalSec
	if interval < 60 {
		interval = 60
	}
	logger.Info("notifier started", "scan_interval_sec", interval)

	ticker := time.NewTicker(time.Duration(interval) * time.Second)
	defer ticker.Stop()

	runCycle := func() {
		now := time.Now()
		count, err := scanner.Run(ctx, now)
		if err != nil {
			logger.Error("scan failed", "error", err)
		} else {
			logger.Info("scan complete", "alerts_processed", count)
		}
		if billing != nil {
			renewed, failed, expired, err := billing.RenewDue(ctx, now.UTC())
			if err != nil {
				logger.Error("billing renew failed", "error", err)
			} else if renewed > 0 || failed > 0 || expired > 0 {
				logger.Info("billing renew", "renewed", renewed, "failed", failed, "expired", expired)
			}
		}
	}

	runCycle()
	for {
		select {
		case <-ctx.Done():
			logger.Info("notifier stopped")
			return
		case <-ticker.C:
			runCycle()
		}
	}
}
