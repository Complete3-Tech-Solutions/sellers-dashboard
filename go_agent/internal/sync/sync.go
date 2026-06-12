// Package sync diffs the watched folder against recorded state and ships the
// changes as a snapshot. Mirrors scc_agent/sync.py, including the force-resync
// path used by admin-requested heartbeat syncs.
package sync

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io/fs"
	"log/slog"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/complete3tech/scc-agent/internal/state"
	"github.com/complete3tech/scc-agent/internal/uploader"
	"github.com/complete3tech/scc-agent/internal/watcher"
)

type Syncer struct {
	folder string
	up     *uploader.Uploader
	store  *state.Store
	mu     sync.Mutex
}

func New(folder string, up *uploader.Uploader, store *state.Store) *Syncer {
	return &Syncer{folder: folder, up: up, store: store}
}

type Result struct {
	SnapshotID string
	Changed    int
	Deleted    int
	Skipped    bool
}

func (s *Syncer) folderHash() string {
	abs, err := filepath.Abs(s.folder)
	if err != nil {
		abs = s.folder
	}
	sum := sha256.Sum256([]byte(abs))
	return hex.EncodeToString(sum[:])
}

// SyncOnce computes the disk-vs-state diff, uploads changes, and commits a
// snapshot. When force is true every current file is re-uploaded regardless of
// its recorded hash. It is a no-op (Skipped) if a sync is already running.
func (s *Syncer) SyncOnce(force bool) (*Result, error) {
	if !s.mu.TryLock() {
		slog.Debug("sync already running, skipping")
		return &Result{Skipped: true}, nil
	}
	defer s.mu.Unlock()

	files, err := watcher.ListXLSX(s.folder)
	if err != nil {
		return nil, err
	}

	type change struct{ path, sha string }
	var changed []change
	current := make(map[string]bool, len(files))
	for _, p := range files {
		name := filepath.Base(p)
		current[name] = true
		h, err := uploader.SHA256File(p)
		if err != nil {
			return nil, err
		}
		prev, err := s.store.Get(name)
		if err != nil {
			return nil, err
		}
		if force || prev == nil || prev.SHA256 != h {
			changed = append(changed, change{path: p, sha: h})
		}
	}

	known, err := s.store.KnownFilenames()
	if err != nil {
		return nil, err
	}
	var deleted []string
	for _, name := range known {
		if !current[name] {
			deleted = append(deleted, name)
		}
	}

	if len(changed) == 0 && len(deleted) == 0 {
		slog.Debug("nothing to do")
		return &Result{}, nil
	}

	slog.Info("starting snapshot", "changed", len(changed), "deleted", len(deleted))
	snapshotID, err := uploader.WithRetry(func() (string, error) {
		return s.up.StartSnapshot(s.folderHash())
	}, 6)
	if err != nil {
		return nil, err
	}

	var manifest []map[string]any
	for _, c := range changed {
		if err := s.uploadWithLockRetry(snapshotID, c.path, c.sha); err != nil {
			return nil, err
		}
		info, err := os.Stat(c.path)
		if err != nil {
			return nil, err
		}
		name := filepath.Base(c.path)
		mtime := float64(info.ModTime().UnixNano()) / 1e9
		if err := s.store.Upsert(name, c.sha, info.Size(), mtime); err != nil {
			return nil, err
		}
		manifest = append(manifest, map[string]any{"filename": name, "sha256": c.sha})
	}

	for _, name := range deleted {
		manifest = append(manifest, map[string]any{"filename": name, "sha256": nil, "deleted": true})
		if err := s.store.Delete(name); err != nil {
			return nil, err
		}
	}

	if _, err := uploader.WithRetry(func() (struct{}, error) {
		_, e := s.up.CommitSnapshot(snapshotID, manifest)
		return struct{}{}, e
	}, 6); err != nil {
		return nil, err
	}
	slog.Info("committed snapshot", "id", snapshotID, "entries", len(manifest))
	return &Result{SnapshotID: snapshotID, Changed: len(changed), Deleted: len(deleted)}, nil
}

// uploadWithLockRetry handles files momentarily locked by Excel: a sharing /
// permission error is retried a few times before giving up.
func (s *Syncer) uploadWithLockRetry(snapshotID, path, sha string) error {
	for attempt := 0; attempt < 3; attempt++ {
		_, err := uploader.WithRetry(func() (struct{}, error) {
			return struct{}{}, s.up.UploadFile(snapshotID, path, sha)
		}, 3)
		if err == nil {
			return nil
		}
		if isLockError(err) {
			time.Sleep(2 * time.Second)
			continue
		}
		return err
	}
	return fmt.Errorf("could not read %s after retries", filepath.Base(path))
}

func isLockError(err error) bool {
	if errors.Is(err, fs.ErrPermission) {
		return true
	}
	return isSharingViolation(err)
}
