// Command scc-agent is the SCC Profitability file-watch agent — a single exe
// that is installer, settings GUI, and background service in one.
//
//	(double-click / no args)  open the settings GUI (Windows)
//	run                       watch the folder and upload (service or foreground)
//	install -key -watch [-url] headless install (config + key + service + shortcuts)
//	uninstall                 full removal (service, shortcuts, Apps & features, data)
//	store-key <key>           persist an API key (scc_live_xxx.yyy) via DPAPI
//	version                   print the version
//
// The legacy installer form `--store-key <key>` is also accepted.
package main

import (
	"flag"
	"fmt"
	"log/slog"
	"os"
	"strings"

	"github.com/getsentry/sentry-go"

	"github.com/complete3tech/scc-agent/internal/config"
	"github.com/complete3tech/scc-agent/internal/creds"
	"github.com/complete3tech/scc-agent/internal/logging"
	"github.com/complete3tech/scc-agent/internal/version"
)

const defaultURL = "https://sellers-dashboard-production.up.railway.app"

func main() { os.Exit(run()) }

func run() int {
	args := os.Args[1:]
	var cmd string
	if len(args) > 0 && !strings.HasPrefix(args[0], "-") {
		cmd, args = args[0], args[1:]
	}

	switch cmd {
	case "store-key":
		if len(args) < 1 {
			fmt.Fprintln(os.Stderr, "usage: scc-agent store-key <key>")
			return 2
		}
		return storeKey(args[0])
	case "install":
		return cmdInstall(args)
	case "uninstall":
		return uninstallFlow()
	case "version":
		fmt.Println(version.Version)
		return 0
	case "run":
		return cmdRun(args)
	case "":
		return cmdDefault(args)
	default:
		fmt.Fprintf(os.Stderr, "unknown command %q\n", cmd)
		return 2
	}
}

// cmdDefault handles invocation with no subcommand: the legacy installer flags,
// otherwise the interactive settings GUI (the double-click experience).
func cmdDefault(args []string) int {
	fs := flag.NewFlagSet("scc-agent", flag.ContinueOnError)
	storeKeyFlag := fs.String("store-key", "", "Persist an API key (legacy installer flag)")
	showVersion := fs.Bool("version", false, "Print version and exit")
	fs.String("config", "", "(ignored here; use `run -config`)")
	if err := fs.Parse(args); err != nil {
		return 2
	}
	if *showVersion {
		fmt.Println(version.Version)
		return 0
	}
	if *storeKeyFlag != "" {
		return storeKey(*storeKeyFlag)
	}
	return launchGUI()
}

// cmdRun runs the agent — under the SCM as a service, or in the foreground.
func cmdRun(args []string) int {
	fs := flag.NewFlagSet("run", flag.ContinueOnError)
	configPath := fs.String("config", "", "Path to config.toml")
	if err := fs.Parse(args); err != nil {
		return 2
	}
	cfg, err := config.Load(*configPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	if err := logging.Setup(config.LogDir, cfg.LogLevel); err != nil {
		fmt.Fprintln(os.Stderr, "logging setup:", err)
		return 1
	}
	initSentry(cfg.SentryDSN)

	if err := platformRun(cfg); err != nil {
		slog.Error("agent exited with error", "err", err)
		return 1
	}
	return 0
}

func storeKey(full string) int {
	if !strings.Contains(full, ".") {
		fmt.Fprintln(os.Stderr, "error: API key must be of the form scc_live_xxx.yyy")
		return 2
	}
	parts := strings.SplitN(full, ".", 2)
	if err := creds.Save(parts[0], parts[1]); err != nil {
		fmt.Fprintln(os.Stderr, "store key:", err)
		return 1
	}
	fmt.Println("Stored.")
	return 0
}

func cmdInstall(args []string) int {
	fs := flag.NewFlagSet("install", flag.ContinueOnError)
	key := fs.String("key", "", "Full API key, scc_live_xxx.yyy")
	watch := fs.String("watch", "", "Absolute path to the folder of job-cost Excel files")
	url := fs.String("url", defaultURL, "API base URL")
	if err := fs.Parse(args); err != nil {
		return 2
	}
	if *key == "" || *watch == "" {
		fmt.Fprintln(os.Stderr, "install requires -key and -watch")
		return 2
	}
	if err := applySettings(*key, *watch, *url); err != nil {
		fmt.Fprintln(os.Stderr, "install:", err)
		return 1
	}
	fmt.Println("Installed and started.")
	return 0
}

func initSentry(dsn string) {
	if dsn == "" {
		return
	}
	if err := sentry.Init(sentry.ClientOptions{
		Dsn:     dsn,
		Release: "scc-agent@" + version.Version,
	}); err != nil {
		slog.Warn("sentry init failed", "err", err)
	}
}
