// Package watcher watches the customer's folder for Excel changes. It combines
// fsnotify (event-driven) with a periodic poll as a safety net, debouncing
// bursts before invoking onChange. Mirrors scc_agent/watcher.py.
package watcher

import (
	"log/slog"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/fsnotify/fsnotify"
)

var xlsxExts = []string{".xlsx", ".xlsm"}

func isExcelTemp(name string) bool {
	return strings.HasPrefix(name, "~$") || strings.HasSuffix(name, ".tmp") || strings.HasSuffix(name, "~")
}

// Customer folders often hold a "Profit_Summary_Template.xlsx" with no real
// data — never ship it.
func isTemplate(name string) bool {
	return strings.Contains(strings.ToLower(name), "template")
}

func hasXLSXExt(name string) bool {
	lower := strings.ToLower(name)
	for _, ext := range xlsxExts {
		if strings.HasSuffix(lower, ext) {
			return true
		}
	}
	return false
}

// ListXLSX returns the shippable Excel files in folder, sorted by full path.
func ListXLSX(folder string) ([]string, error) {
	entries, err := os.ReadDir(folder)
	if err != nil {
		return nil, err
	}
	var out []string
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		name := e.Name()
		if isExcelTemp(name) || isTemplate(name) || !hasXLSXExt(name) {
			continue
		}
		out = append(out, filepath.Join(folder, name))
	}
	sort.Strings(out)
	return out, nil
}

type Watcher struct {
	folder   string
	debounce time.Duration
	poll     time.Duration
	onChange func()

	mu    sync.Mutex
	timer *time.Timer
	stop  chan struct{}
	fsw   *fsnotify.Watcher
}

func New(folder string, debounce, poll time.Duration, onChange func()) *Watcher {
	return &Watcher{
		folder:   folder,
		debounce: debounce,
		poll:     poll,
		onChange: onChange,
		stop:     make(chan struct{}),
	}
}

func (w *Watcher) Start() error {
	if _, err := os.Stat(w.folder); err != nil {
		return err
	}
	fsw, err := fsnotify.NewWatcher()
	if err != nil {
		return err
	}
	if err := fsw.Add(w.folder); err != nil {
		_ = fsw.Close()
		return err
	}
	w.fsw = fsw
	go w.eventLoop()
	go w.pollLoop()
	slog.Info("watching", "folder", w.folder, "debounce", w.debounce, "poll", w.poll)
	return nil
}

func (w *Watcher) eventLoop() {
	for {
		select {
		case <-w.stop:
			return
		case ev, ok := <-w.fsw.Events:
			if !ok {
				return
			}
			name := filepath.Base(ev.Name)
			if isExcelTemp(name) || isTemplate(name) || !hasXLSXExt(name) {
				continue
			}
			w.trigger()
		case err, ok := <-w.fsw.Errors:
			if !ok {
				return
			}
			slog.Warn("fsnotify error", "err", err)
		}
	}
}

func (w *Watcher) pollLoop() {
	t := time.NewTicker(w.poll)
	defer t.Stop()
	for {
		select {
		case <-w.stop:
			return
		case <-t.C:
			w.flush()
		}
	}
}

func (w *Watcher) trigger() {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.timer != nil {
		w.timer.Stop()
	}
	w.timer = time.AfterFunc(w.debounce, w.flush)
}

func (w *Watcher) flush() {
	defer func() {
		if r := recover(); r != nil {
			slog.Error("onChange panicked", "recover", r)
		}
	}()
	w.onChange()
}

func (w *Watcher) Stop() {
	select {
	case <-w.stop:
	default:
		close(w.stop)
	}
	if w.fsw != nil {
		_ = w.fsw.Close()
	}
	w.mu.Lock()
	if w.timer != nil {
		w.timer.Stop()
	}
	w.mu.Unlock()
}
