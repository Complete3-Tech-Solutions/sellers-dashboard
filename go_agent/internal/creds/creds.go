// Package creds stores the agent's API key. On Windows it uses DPAPI
// (LocalMachine scope); on other platforms it falls back to an obfuscated
// dev file. Mirrors scc_agent/creds.py exactly, including the "DEV1" prefix
// and XOR key, so dev cred files remain interchangeable.
package creds

import (
	"encoding/base64"
	"encoding/json"
	"os"

	"github.com/complete3tech/scc-agent/internal/config"
)

const (
	devKey    = "dev-only-not-secure-key-32bytes!"
	devPrefix = "DEV1"
)

type blob struct {
	KeyID  string `json:"key_id"`
	Secret string `json:"secret"`
}

// Save persists the key/secret pair to CredsPath (0600).
func Save(keyID, secret string) error {
	if err := config.EnsureDirs(); err != nil {
		return err
	}
	raw, err := json.Marshal(blob{KeyID: keyID, Secret: secret})
	if err != nil {
		return err
	}
	enc, err := protect(raw)
	if err != nil {
		return err
	}
	return os.WriteFile(config.CredsPath, enc, 0o600)
}

// Load returns (key_id, secret) from CredsPath.
func Load() (string, string, error) {
	enc, err := os.ReadFile(config.CredsPath)
	if err != nil {
		return "", "", err
	}
	dec, err := unprotect(enc)
	if err != nil {
		return "", "", err
	}
	var b blob
	if err := json.Unmarshal(dec, &b); err != nil {
		return "", "", err
	}
	return b.KeyID, b.Secret, nil
}

// TryLoad is Load but reports presence as a bool instead of an error.
func TryLoad() (string, string, bool) {
	k, s, err := Load()
	if err != nil {
		return "", "", false
	}
	return k, s, true
}

func xorBytes(data []byte) []byte {
	key := []byte(devKey)
	out := make([]byte, len(data))
	for i := range data {
		out[i] = data[i] ^ key[i%len(key)]
	}
	return out
}

func devEncode(b []byte) []byte {
	return append([]byte(devPrefix), []byte(base64.StdEncoding.EncodeToString(xorBytes(b)))...)
}

func devDecode(enc []byte) ([]byte, error) {
	raw, err := base64.StdEncoding.DecodeString(string(enc[len(devPrefix):]))
	if err != nil {
		return nil, err
	}
	return xorBytes(raw), nil
}
