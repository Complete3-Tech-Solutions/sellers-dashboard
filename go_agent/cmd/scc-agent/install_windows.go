//go:build windows

package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"

	"github.com/complete3tech/scc-agent/internal/arp"
	"github.com/complete3tech/scc-agent/internal/config"
	"github.com/complete3tech/scc-agent/internal/creds"
	"github.com/complete3tech/scc-agent/internal/service"
	"github.com/complete3tech/scc-agent/internal/version"
)

const (
	shortcutName = "SCC Agent Settings.lnk"
	publisher    = "Complete3 Tech Solutions"
)

// applySettings is the shared install / save-and-restart path used by both the
// GUI and the `install` CLI command. A blank key keeps the stored one. On a
// fresh machine it registers the service, shortcuts, and Apps & features entry;
// when already installed it just rewrites config and restarts the service.
func applySettings(key, folder, url string) error {
	if folder == "" {
		return fmt.Errorf("choose a watch folder")
	}
	if fi, err := os.Stat(folder); err != nil || !fi.IsDir() {
		return fmt.Errorf("watch folder does not exist: %s", folder)
	}
	if url == "" {
		url = defaultURL
	}
	exe, err := os.Executable()
	if err != nil {
		return err
	}

	if err := config.WriteConfig(url, folder); err != nil {
		return fmt.Errorf("write config: %w", err)
	}
	if key != "" {
		if !strings.Contains(key, ".") {
			return fmt.Errorf("API key must look like scc_live_xxx.yyy")
		}
		keyID, secret, _ := strings.Cut(key, ".")
		if err := creds.Save(keyID, secret); err != nil {
			return fmt.Errorf("store key: %w", err)
		}
	} else if _, _, ok := creds.TryLoad(); !ok {
		return fmt.Errorf("enter the API key")
	}

	if installed, _ := service.IsInstalled(); installed {
		if err := service.Restart(); err != nil {
			return fmt.Errorf("restart service: %w", err)
		}
		return nil
	}

	if err := service.Install(exe); err != nil {
		return fmt.Errorf("register service: %w", err)
	}
	createShortcuts(exe)
	_ = arp.Register(arp.Info{
		DisplayName:     "SCC Profitability Agent",
		DisplayVersion:  version.Version,
		Publisher:       publisher,
		InstallLocation: filepath.Dir(exe),
		DisplayIcon:     exe,
		UninstallString: fmt.Sprintf("%q uninstall", exe),
	})
	return nil
}

// uninstallFlow fully removes the agent: service, shortcuts, Apps & features
// entry, and the data directory. Best-effort throughout.
func uninstallFlow() int {
	_ = service.Uninstall()
	removeShortcuts()
	_ = arp.Unregister()
	_ = config.Purge()
	return 0
}

func shortcutPaths() []string {
	var p []string
	if pd := os.Getenv("PROGRAMDATA"); pd != "" {
		p = append(p, filepath.Join(pd, `Microsoft\Windows\Start Menu\Programs`, shortcutName))
	}
	if pub := os.Getenv("PUBLIC"); pub != "" {
		p = append(p, filepath.Join(pub, "Desktop", shortcutName))
	}
	return p
}

// createShortcuts drops "SCC Agent Settings" links (Start Menu + Desktop) that
// reopen this exe with no args — i.e. the settings GUI.
func createShortcuts(target string) {
	for _, lnk := range shortcutPaths() {
		ps := fmt.Sprintf(
			`$s=(New-Object -ComObject WScript.Shell).CreateShortcut(%q);`+
				`$s.TargetPath=%q;$s.WorkingDirectory=%q;$s.IconLocation=%q;`+
				`$s.Description='Configure the SCC Profitability agent';$s.Save()`,
			lnk, target, filepath.Dir(target), target,
		)
		cmd := exec.Command("powershell", "-NoProfile", "-NonInteractive", "-Command", ps)
		cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
		_ = cmd.Run()
	}
}

func removeShortcuts() {
	for _, lnk := range shortcutPaths() {
		_ = os.Remove(lnk)
	}
}
