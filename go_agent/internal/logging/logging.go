// Package logging configures slog with a rotating file handler plus stderr,
// mirroring scc_agent/logging_setup.py (5 MB x 5 backups).
package logging

import (
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"strings"

	lumberjack "gopkg.in/natefinch/lumberjack.v2"
)

func parseLevel(level string) slog.Level {
	switch strings.ToUpper(level) {
	case "DEBUG":
		return slog.LevelDebug
	case "WARNING", "WARN":
		return slog.LevelWarn
	case "ERROR":
		return slog.LevelError
	default:
		return slog.LevelInfo
	}
}

func Setup(logDir, level string) error {
	if err := os.MkdirAll(logDir, 0o755); err != nil {
		return err
	}
	rotating := &lumberjack.Logger{
		Filename:   filepath.Join(logDir, "agent.log"),
		MaxSize:    5, // megabytes
		MaxBackups: 5,
		Compress:   false,
	}
	// File first: in a windowsgui/service process os.Stderr may be an invalid
	// handle, and MultiWriter stops at the first error — so write the file
	// before stderr to guarantee the log file is always written.
	w := io.MultiWriter(rotating, os.Stderr)
	h := slog.NewTextHandler(w, &slog.HandlerOptions{Level: parseLevel(level)})
	slog.SetDefault(slog.New(h))
	return nil
}
