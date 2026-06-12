//go:build !windows

package arp

import "errors"

type Info struct {
	DisplayName     string
	DisplayVersion  string
	Publisher       string
	InstallLocation string
	DisplayIcon     string
	UninstallString string
}

var errUnsupported = errors.New("Add/Remove Programs registration is only available on Windows")

func Register(Info) error { return errUnsupported }
func Unregister() error   { return errUnsupported }
