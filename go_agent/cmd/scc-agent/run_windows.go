//go:build windows

package main

import (
	"context"
	"os"
	"os/signal"
	"syscall"

	"golang.org/x/sys/windows/svc"

	"github.com/complete3tech/scc-agent/internal/app"
	"github.com/complete3tech/scc-agent/internal/config"
	"github.com/complete3tech/scc-agent/internal/service"
)

// platformRun hands off to the SCM when launched as a service, otherwise runs
// in the foreground (e.g. when an operator runs `scc-agent run` in a console).
func platformRun(cfg *config.Config) error {
	isSvc, err := svc.IsWindowsService()
	if err == nil && isSvc {
		return service.Run(cfg)
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	return app.Run(ctx, cfg)
}
