// MoneyPrinterTurbo API 服务入口（对应 Python main.py）。
package main

import (
	"fmt"
	"log/slog"
	"net/http"
	"os"

	"github.com/harry0703/moneyprinterturbo/go/internal/api"
	"github.com/harry0703/moneyprinterturbo/go/internal/config"
)

func main() {
	cfg, err := config.Load()
	if err != nil {
		slog.Error("load config failed", "error", err)
		os.Exit(1)
	}
	addr := fmt.Sprintf("%s:%d", cfg.ListenHost, cfg.ListenPort)
	slog.Info("start server", "docs", "http://127.0.0.1:"+fmt.Sprint(cfg.ListenPort)+"/ping")
	server := api.New(cfg)
	if err := http.ListenAndServe(addr, server.Handler()); err != nil {
		slog.Error("server stopped", "error", err)
		os.Exit(1)
	}
}
