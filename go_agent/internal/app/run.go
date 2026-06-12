// Package app wires the agent's components together and runs the main loop
// until the context is cancelled. Mirrors the cmd_run flow in
// scc_agent/__main__.py (watcher + heartbeat + initial sync).
package app

import (
	"context"
	"log/slog"
	"time"

	"github.com/complete3tech/scc-agent/internal/config"
	"github.com/complete3tech/scc-agent/internal/state"
	syncpkg "github.com/complete3tech/scc-agent/internal/sync"
	"github.com/complete3tech/scc-agent/internal/uploader"
	"github.com/complete3tech/scc-agent/internal/version"
	"github.com/complete3tech/scc-agent/internal/watcher"
)

func secs(v float64) time.Duration {
	return time.Duration(v * float64(time.Second))
}

// Run blocks until ctx is cancelled (signal or service stop).
func Run(ctx context.Context, cfg *config.Config) error {
	slog.Info("scc-agent starting", "version", version.Version, "folder", cfg.WatchFolder)

	store, err := state.New(config.StatePath)
	if err != nil {
		return err
	}
	defer store.Close()

	up := uploader.New(cfg.APIBaseURL)
	syncer := syncpkg.New(cfg.WatchFolder, up, store)

	w := watcher.New(cfg.WatchFolder, secs(cfg.DebounceSecs), secs(cfg.PollInterval), func() {
		if _, err := syncer.SyncOnce(false); err != nil {
			slog.Error("sync failed", "err", err)
		}
	})
	if err := w.Start(); err != nil {
		return err
	}
	defer w.Stop()

	go heartbeatLoop(ctx, up, syncer, secs(cfg.PollInterval))

	// Initial sync so we don't wait for the first edit.
	if _, err := syncer.SyncOnce(false); err != nil {
		slog.Error("initial sync failed", "err", err)
	}

	<-ctx.Done()
	slog.Info("shutdown signal received; stopping")
	return nil
}

// heartbeatLoop pings the server every interval for liveness and to pick up
// admin-requested syncs. Failures are non-fatal — the agent keeps watching.
func heartbeatLoop(ctx context.Context, up *uploader.Uploader, syncer *syncpkg.Syncer, interval time.Duration) {
	t := time.NewTicker(interval)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			resp, err := up.Heartbeat()
			if err != nil {
				slog.Debug("heartbeat failed", "err", err)
				continue
			}
			if v, ok := resp["sync"].(bool); ok && v {
				slog.Info("server requested an on-demand sync")
				if _, err := syncer.SyncOnce(true); err != nil {
					slog.Error("requested sync failed", "err", err)
				}
			}
		}
	}
}
