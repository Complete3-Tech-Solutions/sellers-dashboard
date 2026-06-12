//go:build windows

package sync

import (
	"errors"

	"golang.org/x/sys/windows"
)

// ERROR_SHARING_VIOLATION (32) is what Windows returns when Excel holds the
// file open with an exclusive lock.
func isSharingViolation(err error) bool {
	return errors.Is(err, windows.ERROR_SHARING_VIOLATION)
}
