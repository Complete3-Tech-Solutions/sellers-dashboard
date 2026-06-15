//go:build !windows

package service

import (
	"errors"

	"github.com/complete3tech/scc-agent/internal/config"
)

// Name is referenced by the CLI on all platforms.
const Name = "SCCAgent"

var errUnsupported = errors.New("Windows service management is only available on Windows")

func Run(*config.Config) error    { return errUnsupported }
func Install(string) error        { return errUnsupported }
func Uninstall() error            { return errUnsupported }
func Restart() error              { return errUnsupported }
func IsInstalled() (bool, error)  { return false, errUnsupported }
