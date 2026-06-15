//go:build windows

package creds

import (
	"bytes"
	"fmt"
	"unsafe"

	"golang.org/x/sys/windows"
)

var (
	crypt32            = windows.NewLazySystemDLL("crypt32.dll")
	procCryptProtect   = crypt32.NewProc("CryptProtectData")
	procCryptUnprotect = crypt32.NewProc("CryptUnprotectData")
	kernel32           = windows.NewLazySystemDLL("kernel32.dll")
	procLocalFree      = kernel32.NewProc("LocalFree")
)

// CRYPTPROTECT_LOCAL_MACHINE (0x4) — matches the flag passed in creds.py so
// the SYSTEM service account can decrypt what the installer wrote.
const cryptProtectLocalMachine = 0x4

type dataBlob struct {
	cbData uint32
	pbData *byte
}

func (b *dataBlob) toBytes() []byte {
	out := make([]byte, b.cbData)
	copy(out, unsafe.Slice(b.pbData, b.cbData))
	return out
}

func newBlob(data []byte) dataBlob {
	if len(data) == 0 {
		return dataBlob{}
	}
	return dataBlob{cbData: uint32(len(data)), pbData: &data[0]}
}

func protect(data []byte) ([]byte, error) {
	in := newBlob(data)
	var out dataBlob
	r, _, err := procCryptProtect.Call(
		uintptr(unsafe.Pointer(&in)),
		0, 0, 0, 0,
		cryptProtectLocalMachine,
		uintptr(unsafe.Pointer(&out)),
	)
	if r == 0 {
		return nil, fmt.Errorf("CryptProtectData: %w", err)
	}
	defer procLocalFree.Call(uintptr(unsafe.Pointer(out.pbData)))
	return out.toBytes(), nil
}

func unprotect(enc []byte) ([]byte, error) {
	// A dev-written file (e.g. copied from a non-Windows box) is XOR, not DPAPI.
	if bytes.HasPrefix(enc, []byte(devPrefix)) {
		return devDecode(enc)
	}
	in := newBlob(enc)
	var out dataBlob
	r, _, err := procCryptUnprotect.Call(
		uintptr(unsafe.Pointer(&in)),
		0, 0, 0, 0,
		0,
		uintptr(unsafe.Pointer(&out)),
	)
	if r == 0 {
		return nil, fmt.Errorf("CryptUnprotectData: %w", err)
	}
	defer procLocalFree.Call(uintptr(unsafe.Pointer(out.pbData)))
	return out.toBytes(), nil
}
