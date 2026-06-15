package uploader

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"testing"
)

// Verifies the signature is computed over METHOD\nPATH\nTS\nNONCE\nSHA256(body),
// matching the server's expectation (and scc_agent/uploader.py).
func TestBuildHeadersSignature(t *testing.T) {
	const (
		keyID  = "scc_live_abc"
		secret = "supersecret"
		method = "POST"
		path   = "/api/snapshot/start"
	)
	body := []byte(`{"hello":"world"}`)
	h := buildHeaders(method, path, body, keyID, secret)

	if got := h["Authorization"]; got != "Bearer "+keyID+"."+secret {
		t.Fatalf("Authorization = %q", got)
	}
	for _, k := range []string{"X-Timestamp", "X-Nonce", "X-Signature", "User-Agent"} {
		if h[k] == "" {
			t.Fatalf("missing header %s", k)
		}
	}

	bh := sha256.Sum256(body)
	msg := method + "\n" + path + "\n" + h["X-Timestamp"] + "\n" + h["X-Nonce"] + "\n" + hex.EncodeToString(bh[:])
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(msg))
	want := hex.EncodeToString(mac.Sum(nil))
	if h["X-Signature"] != want {
		t.Fatalf("signature mismatch:\n got %s\nwant %s", h["X-Signature"], want)
	}
}

func TestRandUUIDFormat(t *testing.T) {
	u := randUUID()
	if len(u) != 36 || u[8] != '-' || u[13] != '-' || u[18] != '-' || u[23] != '-' {
		t.Fatalf("not a uuid: %q", u)
	}
	if u[14] != '4' {
		t.Fatalf("expected version 4 nibble, got %q", u)
	}
}
