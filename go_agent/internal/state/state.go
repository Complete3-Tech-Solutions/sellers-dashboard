// Package state is the agent's local record of what it has uploaded, backed by
// SQLite via the pure-Go modernc driver (no CGo). Mirrors scc_agent/state.py.
package state

import (
	"database/sql"
	"errors"
	"os"
	"path/filepath"

	_ "modernc.org/sqlite"
)

type FileState struct {
	Filename  string
	SHA256    string
	SizeBytes int64
	Mtime     float64
}

type Store struct {
	db *sql.DB
}

func New(path string) (*Store, error) {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return nil, err
	}
	db, err := sql.Open("sqlite", path)
	if err != nil {
		return nil, err
	}
	s := &Store{db: db}
	if err := s.init(); err != nil {
		_ = db.Close()
		return nil, err
	}
	return s, nil
}

func (s *Store) Close() error { return s.db.Close() }

func (s *Store) init() error {
	_, err := s.db.Exec(`
		CREATE TABLE IF NOT EXISTS file_state (
			filename TEXT PRIMARY KEY,
			sha256 TEXT NOT NULL,
			size_bytes INTEGER NOT NULL,
			mtime REAL NOT NULL,
			uploaded_at TEXT NOT NULL
		);
		CREATE TABLE IF NOT EXISTS retry_queue (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			snapshot_id TEXT,
			filename TEXT,
			payload BLOB,
			attempts INTEGER NOT NULL DEFAULT 0,
			next_try_at TEXT NOT NULL,
			last_error TEXT
		);`)
	return err
}

// Get returns the recorded state for a filename, or (nil, nil) if unknown.
func (s *Store) Get(filename string) (*FileState, error) {
	row := s.db.QueryRow(
		"SELECT filename, sha256, size_bytes, mtime FROM file_state WHERE filename = ?",
		filename,
	)
	var fs FileState
	err := row.Scan(&fs.Filename, &fs.SHA256, &fs.SizeBytes, &fs.Mtime)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &fs, nil
}

func (s *Store) Upsert(filename, sha256 string, sizeBytes int64, mtime float64) error {
	_, err := s.db.Exec(`
		INSERT INTO file_state(filename, sha256, size_bytes, mtime, uploaded_at)
		VALUES (?, ?, ?, ?, datetime('now'))
		ON CONFLICT(filename) DO UPDATE SET
			sha256=excluded.sha256,
			size_bytes=excluded.size_bytes,
			mtime=excluded.mtime,
			uploaded_at=datetime('now')`,
		filename, sha256, sizeBytes, mtime,
	)
	return err
}

func (s *Store) Delete(filename string) error {
	_, err := s.db.Exec("DELETE FROM file_state WHERE filename = ?", filename)
	return err
}

func (s *Store) KnownFilenames() ([]string, error) {
	rows, err := s.db.Query("SELECT filename FROM file_state")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			return nil, err
		}
		out = append(out, name)
	}
	return out, rows.Err()
}
