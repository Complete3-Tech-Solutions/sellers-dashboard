//go:build !windows

package main

import (
	"fmt"
	"os"
)

func launchGUI() int {
	fmt.Fprintln(os.Stderr, "the settings GUI is only available on Windows; use `scc-agent run` to run the agent")
	return 1
}
