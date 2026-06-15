//go:build windows

// Package service runs the agent as a native Windows service and registers /
// removes it. This replaces NSSM entirely — the binary is its own service host.
package service

import (
	"context"
	"fmt"
	"time"

	"golang.org/x/sys/windows/svc"
	"golang.org/x/sys/windows/svc/mgr"

	"github.com/complete3tech/scc-agent/internal/app"
	"github.com/complete3tech/scc-agent/internal/config"
)

const (
	Name        = "SCCAgent"
	displayName = "SCC Profitability Agent"
	description = "Uploads SCC job-cost Excel changes to the SCC Profitability SaaS"
)

type handler struct {
	cfg *config.Config
}

func (h *handler) Execute(_ []string, r <-chan svc.ChangeRequest, status chan<- svc.Status) (bool, uint32) {
	const accepted = svc.AcceptStop | svc.AcceptShutdown
	status <- svc.Status{State: svc.StartPending}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	errc := make(chan error, 1)
	go func() { errc <- app.Run(ctx, h.cfg) }()

	status <- svc.Status{State: svc.Running, Accepts: accepted}
	for {
		select {
		case c := <-r:
			switch c.Cmd {
			case svc.Interrogate:
				status <- c.CurrentStatus
			case svc.Stop, svc.Shutdown:
				cancel()
				status <- svc.Status{State: svc.StopPending}
				<-errc
				return false, 0
			}
		case err := <-errc:
			if err != nil {
				return false, 1
			}
			return false, 0
		}
	}
}

// Run hands control to the SCM (called when started as a service).
func Run(cfg *config.Config) error {
	return svc.Run(Name, &handler{cfg: cfg})
}

// Install registers the service to auto-start and run `exePath run`.
func Install(exePath string) error {
	m, err := mgr.Connect()
	if err != nil {
		return err
	}
	defer m.Disconnect()

	if s, err := m.OpenService(Name); err == nil {
		s.Close()
		return fmt.Errorf("service %s already exists", Name)
	}
	s, err := m.CreateService(Name, exePath, mgr.Config{
		StartType:        mgr.StartAutomatic,
		DisplayName:      displayName,
		Description:      description,
		DelayedAutoStart: true,
	}, "run")
	if err != nil {
		return err
	}
	defer s.Close()

	// Auto-restart on crash so the agent self-heals (5s, 5s, then 30s; the
	// failure count resets after a day of healthy uptime).
	_ = s.SetRecoveryActions([]mgr.RecoveryAction{
		{Type: mgr.ServiceRestart, Delay: 5 * time.Second},
		{Type: mgr.ServiceRestart, Delay: 5 * time.Second},
		{Type: mgr.ServiceRestart, Delay: 30 * time.Second},
	}, 86400)

	return s.Start("run")
}

// IsInstalled reports whether the service is registered.
func IsInstalled() (bool, error) {
	m, err := mgr.Connect()
	if err != nil {
		return false, err
	}
	defer m.Disconnect()
	s, err := m.OpenService(Name)
	if err != nil {
		return false, nil
	}
	s.Close()
	return true, nil
}

// Restart stops (waiting for the stop to take effect) then starts the service,
// so a config change is picked up.
func Restart() error {
	m, err := mgr.Connect()
	if err != nil {
		return err
	}
	defer m.Disconnect()
	s, err := m.OpenService(Name)
	if err != nil {
		return fmt.Errorf("service %s not installed: %w", Name, err)
	}
	defer s.Close()

	if st, err := s.Control(svc.Stop); err == nil {
		deadline := time.Now().Add(15 * time.Second)
		for st.State != svc.Stopped && time.Now().Before(deadline) {
			time.Sleep(300 * time.Millisecond)
			if st, err = s.Query(); err != nil {
				break
			}
		}
	}
	return s.Start("run")
}

func Uninstall() error {
	m, err := mgr.Connect()
	if err != nil {
		return err
	}
	defer m.Disconnect()

	s, err := m.OpenService(Name)
	if err != nil {
		return fmt.Errorf("service %s not installed: %w", Name, err)
	}
	defer s.Close()
	_, _ = s.Control(svc.Stop)
	return s.Delete()
}
