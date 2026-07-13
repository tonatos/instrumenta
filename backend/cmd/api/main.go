package main

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/app"
	"github.com/tonatos/bond-monitor/backend/internal/interfaces/config"
	applogging "github.com/tonatos/bond-monitor/backend/internal/interfaces/logging"
	httpapi "github.com/tonatos/bond-monitor/backend/internal/interfaces/http"
)

func main() {
	settings := config.Load()
	logger := applogging.New(settings.LogLevel, settings.Debug)
	slog.SetDefault(logger)

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	logger.Info("starting bond-monitor API",
		"host", settings.Host,
		"port", settings.Port,
		"log_level", settings.LogLevel,
		"debug", settings.Debug,
		"auth", settings.AuthEnabled(),
		"redis", settings.RedisURL != "",
		"trading_sandbox", settings.TTradingTokenSandbox != "",
		"trading_production", settings.TTradingTokenProduction != "",
	)

	runtime, err := app.Wire(ctx, settings, logger)
	if err != nil {
		logger.Error("wire failed", "error", err)
		os.Exit(1)
	}
	defer func() { _ = runtime.DB.Close() }()

	if err := runtime.Consumer.Start(ctx); err != nil {
		logger.Warn("notification consumer start failed", "error", err)
	}
	defer func() {
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = runtime.Consumer.Stop(shutdownCtx)
	}()

	router := httpapi.NewRouter(runtime.Deps, logger)
	addr := fmt.Sprintf("%s:%d", settings.Host, settings.Port)
	server := &http.Server{
		Addr:              addr,
		Handler:           router,
		ReadHeaderTimeout: 10 * time.Second,
	}

	go func() {
		logger.Info("listening", "addr", addr)
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logger.Error("server failed", "error", err)
			os.Exit(1)
		}
	}()

	<-ctx.Done()
	logger.Info("shutting down")
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := server.Shutdown(shutdownCtx); err != nil {
		logger.Warn("shutdown error", "error", err)
	}
}
