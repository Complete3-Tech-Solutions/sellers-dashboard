//go:build !windows

package sync

// No Windows-style sharing violations off Windows; fs.ErrPermission (checked by
// the caller) is enough.
func isSharingViolation(error) bool { return false }
