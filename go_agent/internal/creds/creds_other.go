//go:build !windows

package creds

import (
	"bytes"
	"errors"
)

// On non-Windows platforms we only support the obfuscated dev format. This
// matches creds.py, which uses DPAPI solely on win32.
func protect(data []byte) ([]byte, error) {
	return devEncode(data), nil
}

func unprotect(enc []byte) ([]byte, error) {
	if !bytes.HasPrefix(enc, []byte(devPrefix)) {
		return nil, errors.New("creds: DPAPI-encrypted file requires Windows")
	}
	return devDecode(enc)
}
