// Package uploader signs and sends snapshot requests to the SCC backend.
// Every request carries the HMAC headers the server expects (X-Timestamp,
// X-Nonce, X-Signature over METHOD\nPATH\nTS\nNONCE\nSHA256(body)).
// Mirrors scc_agent/uploader.py.
package uploader

import (
	"bytes"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"time"

	"github.com/complete3tech/scc-agent/internal/creds"
	"github.com/complete3tech/scc-agent/internal/version"
)

// HTTPError is returned for any non-2xx response. Permanent() distinguishes
// the fatal 4xx (non-429) case from retryable failures.
type HTTPError struct {
	Status int
	Body   string
}

func (e *HTTPError) Error() string { return fmt.Sprintf("http %d: %s", e.Status, e.Body) }

func (e *HTTPError) Permanent() bool {
	return e.Status >= 400 && e.Status < 500 && e.Status != 429
}

type Uploader struct {
	BaseURL string
	client  *http.Client
	creds   func() (string, string, error)
}

func New(baseURL string) *Uploader {
	return &Uploader{
		BaseURL: baseURL,
		client:  &http.Client{Timeout: 60 * time.Second},
		creds:   creds.Load,
	}
}

func randHex(n int) string {
	b := make([]byte, n)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

func randUUID() string {
	b := make([]byte, 16)
	_, _ = rand.Read(b)
	b[6] = (b[6] & 0x0f) | 0x40
	b[8] = (b[8] & 0x3f) | 0x80
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:16])
}

func buildHeaders(method, path string, body []byte, keyID, secret string) map[string]string {
	ts := strconv.FormatInt(time.Now().Unix(), 10)
	nonce := randUUID()
	bh := sha256.Sum256(body)
	msg := method + "\n" + path + "\n" + ts + "\n" + nonce + "\n" + hex.EncodeToString(bh[:])
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(msg))
	return map[string]string{
		"Authorization": "Bearer " + keyID + "." + secret,
		"X-Timestamp":   ts,
		"X-Nonce":       nonce,
		"X-Signature":   hex.EncodeToString(mac.Sum(nil)),
		"User-Agent":    fmt.Sprintf("scc-agent/%s (%s/%s)", version.Version, runtime.GOOS, runtime.GOARCH),
	}
}

// request signs and sends; on a non-2xx status it drains the body and returns
// an *HTTPError. On success the caller owns resp.Body.
func (u *Uploader) request(method, path string, body []byte, contentType string) (*http.Response, error) {
	keyID, secret, err := u.creds()
	if err != nil {
		return nil, fmt.Errorf("load creds: %w", err)
	}
	headers := buildHeaders(method, path, body, keyID, secret)
	var rdr io.Reader
	if len(body) > 0 {
		rdr = bytes.NewReader(body)
	}
	req, err := http.NewRequest(method, u.BaseURL+path, rdr)
	if err != nil {
		return nil, err
	}
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	resp, err := u.client.Do(req)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		b, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		resp.Body.Close()
		return nil, &HTTPError{Status: resp.StatusCode, Body: string(b)}
	}
	return resp, nil
}

func (u *Uploader) requestJSON(method, path string, body []byte, contentType string) (map[string]any, error) {
	resp, err := u.request(method, path, body, contentType)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var m map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&m); err != nil && !errors.Is(err, io.EOF) {
		return nil, err
	}
	return m, nil
}

func (u *Uploader) StartSnapshot(folderHash string) (string, error) {
	body, _ := json.Marshal(map[string]any{
		"agent_version":    version.Version,
		"folder_path_hash": folderHash,
	})
	m, err := u.requestJSON("POST", "/api/snapshot/start", body, "application/json")
	if err != nil {
		return "", err
	}
	id, _ := m["snapshot_id"].(string)
	if id == "" {
		return "", fmt.Errorf("snapshot/start returned no snapshot_id")
	}
	return id, nil
}

// UploadFile assembles the multipart body by hand so the bytes we sign are the
// exact bytes we send (the signature covers the assembled body).
func (u *Uploader) UploadFile(snapshotID, path, sha256hex string) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	name := filepath.Base(path)
	boundary := "----scc" + randHex(8)
	var buf bytes.Buffer
	field := func(fieldName, value string) {
		fmt.Fprintf(&buf, "--%s\r\nContent-Disposition: form-data; name=%q\r\n\r\n%s\r\n", boundary, fieldName, value)
	}
	field("filename", name)
	field("sha256", sha256hex)
	fmt.Fprintf(&buf,
		"--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=%q\r\n"+
			"Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n",
		boundary, name)
	buf.Write(data)
	fmt.Fprintf(&buf, "\r\n--%s--\r\n", boundary)

	resp, err := u.request("POST", "/api/snapshot/"+snapshotID+"/file", buf.Bytes(),
		"multipart/form-data; boundary="+boundary)
	if err != nil {
		return err
	}
	resp.Body.Close()
	return nil
}

func (u *Uploader) CommitSnapshot(snapshotID string, manifest []map[string]any) (map[string]any, error) {
	body, _ := json.Marshal(map[string]any{"manifest": manifest})
	return u.requestJSON("POST", "/api/snapshot/"+snapshotID+"/commit", body, "application/json")
}

func (u *Uploader) SnapshotStatus(snapshotID string) (map[string]any, error) {
	return u.requestJSON("GET", "/api/snapshot/"+snapshotID, nil, "")
}

// Heartbeat pings the server (signed, empty body) for liveness and to learn
// whether an admin requested an on-demand sync.
func (u *Uploader) Heartbeat() (map[string]any, error) {
	return u.requestJSON("POST", "/api/snapshot/heartbeat", nil, "")
}

// SHA256File streams the file's SHA-256, hex-encoded.
func SHA256File(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

// WithRetry runs fn with exponential backoff. A permanent 4xx (non-429) error
// aborts immediately; everything else is retried up to maxAttempts.
func WithRetry[T any](fn func() (T, error), maxAttempts int) (T, error) {
	delays := []time.Duration{
		1 * time.Second, 5 * time.Second, 30 * time.Second,
		5 * time.Minute, 30 * time.Minute, 2 * time.Hour,
	}
	var zero T
	for attempt := 0; attempt < maxAttempts; attempt++ {
		v, err := fn()
		if err == nil {
			return v, nil
		}
		var he *HTTPError
		if errors.As(err, &he) && he.Permanent() {
			slog.Error("permanent error", "status", he.Status, "body", he.Body)
			return zero, err
		}
		wait := delays[min(attempt, len(delays)-1)]
		slog.Warn("transient error, backing off", "attempt", attempt+1, "sleep", wait, "err", err)
		time.Sleep(wait)
	}
	return zero, fmt.Errorf("max retries exhausted")
}
