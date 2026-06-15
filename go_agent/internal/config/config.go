// Package config resolves the agent's data directory and loads config.toml.
// Mirrors scc_agent/config.py: data lives under %PROGRAMDATA%\SCCAgent on
// Windows (or ~/SCCAgent elsewhere for development).
package config

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/BurntSushi/toml"
)

func dataDir() string {
	base := os.Getenv("PROGRAMDATA")
	if base == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			home = "."
		}
		base = home
	}
	return filepath.Join(base, "SCCAgent")
}

var (
	DataDir    = dataDir()
	ConfigPath = filepath.Join(DataDir, "config.toml")
	CredsPath  = filepath.Join(DataDir, "creds.bin")
	StatePath  = filepath.Join(DataDir, "state.db")
	LogDir     = filepath.Join(DataDir, "logs")
)

type Config struct {
	APIBaseURL   string
	WatchFolder  string
	DebounceSecs float64
	PollInterval float64
	LogLevel     string
	SentryDSN    string
	// ExcludedFiles are base filenames the user deselected in the settings GUI;
	// the syncer treats them as absent (never uploaded).
	ExcludedFiles []string
	// IncludedFiles are base filenames the user added explicitly. The syncer
	// uploads them even if the default pattern would skip them (e.g. a file with
	// "template" in its name), as long as they exist in the watch folder.
	IncludedFiles []string
}

type rawConfig struct {
	APIBaseURL    string   `toml:"api_base_url"`
	WatchFolder   string   `toml:"watch_folder"`
	DebounceSecs  float64  `toml:"debounce_secs"`
	PollInterval  float64  `toml:"poll_interval"`
	LogLevel      string   `toml:"log_level"`
	SentryDSN     string   `toml:"sentry_dsn"`
	ExcludedFiles []string `toml:"excluded_files"`
	IncludedFiles []string `toml:"included_files"`
}

// Load reads config.toml. An empty path uses the default ConfigPath.
func Load(path string) (*Config, error) {
	if path == "" {
		path = ConfigPath
	}
	if _, err := os.Stat(path); err != nil {
		return nil, fmt.Errorf("config not found at %s. Run install first", path)
	}
	raw := rawConfig{DebounceSecs: 8, PollInterval: 30, LogLevel: "INFO"}
	if _, err := toml.DecodeFile(path, &raw); err != nil {
		return nil, fmt.Errorf("parse %s: %w", path, err)
	}
	if raw.APIBaseURL == "" || raw.WatchFolder == "" {
		return nil, fmt.Errorf("api_base_url and watch_folder are required in %s", path)
	}
	return &Config{
		APIBaseURL:    strings.TrimRight(raw.APIBaseURL, "/"),
		WatchFolder:   raw.WatchFolder,
		DebounceSecs:  raw.DebounceSecs,
		PollInterval:  raw.PollInterval,
		LogLevel:      strings.ToUpper(raw.LogLevel),
		SentryDSN:     raw.SentryDSN,
		ExcludedFiles: raw.ExcludedFiles,
		IncludedFiles: raw.IncludedFiles,
	}, nil
}

// EnsureDirs creates the data and log directories (mirrors ensure_dirs()).
func EnsureDirs() error {
	if err := os.MkdirAll(DataDir, 0o755); err != nil {
		return err
	}
	return os.MkdirAll(LogDir, 0o755)
}

// Purge removes the entire data directory (config, creds, state, logs). Used
// when fully uninstalling.
func Purge() error {
	return os.RemoveAll(DataDir)
}

// WriteConfig writes a fresh config.toml (used by the `install` subcommand and
// the settings GUI). excluded lists base filenames to skip; included lists ones
// to upload even if the default pattern would skip them.
func WriteConfig(apiBaseURL, watchFolder string, excluded, included []string) error {
	if err := EnsureDirs(); err != nil {
		return err
	}
	content := fmt.Sprintf(
		"api_base_url  = %q\nwatch_folder  = %q\ndebounce_secs = 8\npoll_interval = 30\nlog_level     = \"INFO\"\nexcluded_files = %s\nincluded_files = %s\n",
		apiBaseURL, watchFolder, tomlStringArray(excluded), tomlStringArray(included),
	)
	return os.WriteFile(ConfigPath, []byte(content), 0o644)
}

// tomlStringArray renders a []string as a TOML inline array, e.g. ["a", "b"].
func tomlStringArray(items []string) string {
	if len(items) == 0 {
		return "[]"
	}
	parts := make([]string, len(items))
	for i, s := range items {
		parts[i] = strconv.Quote(s)
	}
	return "[" + strings.Join(parts, ", ") + "]"
}
