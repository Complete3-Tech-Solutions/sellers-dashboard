//go:build windows

// Package arp registers the agent in Windows "Apps & features" (the Add/Remove
// Programs list) so it can be uninstalled the native way. This is a lightweight
// alternative to shipping an MSI: we just write the standard Uninstall registry
// key. The UninstallString points back at the elevated setup exe.
package arp

import "golang.org/x/sys/windows/registry"

const keyPath = `SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\SCCAgent`

type Info struct {
	DisplayName     string
	DisplayVersion  string
	Publisher       string
	InstallLocation string
	DisplayIcon     string
	UninstallString string
}

// Register writes (or overwrites) the ARP entry under HKLM.
func Register(i Info) error {
	k, _, err := registry.CreateKey(registry.LOCAL_MACHINE, keyPath, registry.SET_VALUE)
	if err != nil {
		return err
	}
	defer k.Close()

	strs := map[string]string{
		"DisplayName":          i.DisplayName,
		"DisplayVersion":       i.DisplayVersion,
		"Publisher":            i.Publisher,
		"InstallLocation":      i.InstallLocation,
		"DisplayIcon":          i.DisplayIcon,
		"UninstallString":      i.UninstallString,
		"QuietUninstallString": i.UninstallString + " /quiet",
	}
	for name, val := range strs {
		if val == "" {
			continue
		}
		if err := k.SetStringValue(name, val); err != nil {
			return err
		}
	}
	// Uninstall-only entry: no Change/Repair buttons.
	if err := k.SetDWordValue("NoModify", 1); err != nil {
		return err
	}
	return k.SetDWordValue("NoRepair", 1)
}

// Unregister removes the ARP entry. A missing key is not an error.
func Unregister() error {
	err := registry.DeleteKey(registry.LOCAL_MACHINE, keyPath)
	if err == registry.ErrNotExist {
		return nil
	}
	return err
}
