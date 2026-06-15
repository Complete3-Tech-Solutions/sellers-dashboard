//go:build !windows

package main

import (
	"errors"
	"fmt"
	"os"
)

var errWindowsOnly = errors.New("install/uninstall is only supported on Windows")

func applySettings(string, string, string, []string, []string) error { return errWindowsOnly }

func uninstallFlow() int {
	fmt.Fprintln(os.Stderr, errWindowsOnly)
	return 1
}
