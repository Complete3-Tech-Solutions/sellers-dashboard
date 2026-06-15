//go:build windows

package main

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/lxn/walk"
	. "github.com/lxn/walk/declarative"

	"github.com/complete3tech/scc-agent/internal/config"
	"github.com/complete3tech/scc-agent/internal/creds"
	"github.com/complete3tech/scc-agent/internal/service"
	"github.com/complete3tech/scc-agent/internal/version"
	"github.com/complete3tech/scc-agent/internal/watcher"
)

// fileListModel backs the env-PATH-style file list in the settings GUI. It
// shows the exact set of files that will be uploaded: the watch folder's
// pattern-matched files, plus explicit includes, minus removed (excluded) ones.
type fileListModel struct {
	walk.TableModelBase
	names []string
}

func (m *fileListModel) RowCount() int { return len(m.names) }

func (m *fileListModel) Value(row, _ int) interface{} { return m.names[row] }

// rebuild rescans folder and recomputes the visible upload set from the current
// excluded / included sets, so the list always reflects what the agent will send.
func (m *fileListModel) rebuild(folder string, excluded, included map[string]bool) {
	set := map[string]bool{}
	if folder != "" {
		if paths, err := watcher.ListXLSX(folder); err == nil {
			for _, p := range paths {
				if name := filepath.Base(p); !excluded[name] {
					set[name] = true
				}
			}
		}
		for name := range included {
			if excluded[name] {
				continue
			}
			if _, err := os.Stat(filepath.Join(folder, name)); err == nil {
				set[name] = true
			}
		}
	}
	m.names = m.names[:0]
	for name := range set {
		m.names = append(m.names, name)
	}
	sort.Strings(m.names)
	m.PublishRowsReset()
}

// sameFolder reports whether file sits directly in folder (case-insensitive,
// matching Windows path semantics).
func sameFolder(file, folder string) bool {
	return strings.EqualFold(filepath.Clean(filepath.Dir(file)), filepath.Clean(folder))
}

// sortedKeys returns the keys of a string set in stable order.
func sortedKeys(set map[string]bool) []string {
	out := make([]string, 0, len(set))
	for k := range set {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

// launchGUI shows the installer / settings window. On a fresh machine the
// button reads "Install"; once installed it reads "Save & Restart" and the
// current folder/URL are pre-filled.
func launchGUI() int {
	existing, _ := config.Load("")
	_, _, haveKey := creds.TryLoad()
	installed, _ := service.IsInstalled()

	initFolder, initURL := "", defaultURL
	if existing != nil {
		initFolder = existing.WatchFolder
		if existing.APIBaseURL != "" {
			initURL = existing.APIBaseURL
		}
	}
	keyCue := "scc_live_xxxxxxxx.yyyyyyyyyyyy"
	if haveKey {
		keyCue = "leave blank to keep the current key"
	}
	// "&&" renders as a literal "&" (a single "&" is a Win32 accelerator).
	btnText := "Install"
	if installed {
		btnText = "Save && Restart"
	}

	excludedSet := map[string]bool{}
	includedSet := map[string]bool{}
	if existing != nil {
		for _, n := range existing.ExcludedFiles {
			excludedSet[n] = true
		}
		for _, n := range existing.IncludedFiles {
			includedSet[n] = true
		}
	}
	filesModel := &fileListModel{}
	filesModel.rebuild(initFolder, excludedSet, includedSet)

	var (
		mw         *walk.MainWindow
		keyEdit    *walk.LineEdit
		folderEdit *walk.LineEdit
		urlEdit    *walk.LineEdit
		filesTV    *walk.TableView
		status     *walk.Label
		actionBtn  *walk.PushButton
	)

	refresh := func() {
		filesModel.rebuild(strings.TrimSpace(folderEdit.Text()), excludedSet, includedSet)
	}

	browse := func() {
		dlg := &walk.FileDialog{Title: "Select the folder of job-cost Excel files"}
		if ok, err := dlg.ShowBrowseFolder(mw); err == nil && ok {
			folderEdit.SetText(dlg.FilePath)
			refresh()
		}
	}

	// addFile lets the operator add an Excel file from the watch folder that the
	// default pattern skipped, or re-add one they previously removed.
	addFile := func() {
		folder := strings.TrimSpace(folderEdit.Text())
		if folder == "" {
			walk.MsgBox(mw, "No folder", "Choose a watch folder first.", walk.MsgBoxIconWarning)
			return
		}
		dlg := &walk.FileDialog{
			Title:          "Add an Excel file from the watch folder",
			Filter:         "Excel files (*.xlsx;*.xlsm)|*.xlsx;*.xlsm|All files (*.*)|*.*",
			InitialDirPath: folder,
		}
		if ok, err := dlg.ShowOpen(mw); err != nil || !ok {
			return
		}
		if !sameFolder(dlg.FilePath, folder) {
			walk.MsgBox(mw, "Outside the watch folder",
				"Pick a file inside the watch folder:\n"+folder, walk.MsgBoxIconWarning)
			return
		}
		name := filepath.Base(dlg.FilePath)
		delete(excludedSet, name)
		includedSet[name] = true
		refresh()
	}

	// removeFile drops the selected file from the upload list (records it as
	// excluded; it stops uploading and is removed server-side on the next sync).
	removeFile := func() {
		i := filesTV.CurrentIndex()
		if i < 0 || i >= len(filesModel.names) {
			walk.MsgBox(mw, "Nothing selected",
				"Select a file in the list to remove it from the upload set.", walk.MsgBoxIconInformation)
			return
		}
		name := filesModel.names[i]
		excludedSet[name] = true
		delete(includedSet, name)
		refresh()
	}

	apply := func() {
		actionBtn.SetEnabled(false)
		status.SetText("Working…")
		err := applySettings(
			strings.TrimSpace(keyEdit.Text()),
			strings.TrimSpace(folderEdit.Text()),
			strings.TrimSpace(urlEdit.Text()),
			sortedKeys(excludedSet),
			sortedKeys(includedSet),
		)
		actionBtn.SetEnabled(true)
		if err != nil {
			status.SetText("Failed: " + err.Error())
			walk.MsgBox(mw, "Failed", err.Error(), walk.MsgBoxIconError)
			return
		}
		actionBtn.SetText("Save && Restart")
		status.SetText("Saved — the agent is watching the folder.")
		walk.MsgBox(mw, "Done",
			"SCC Agent is installed and running.\nIt will watch the selected folder.",
			walk.MsgBoxIconInformation)
	}

	_, err := (MainWindow{
		AssignTo: &mw,
		Title:    "SCC Agent Settings " + version.Version,
		Size:     Size{Width: 600, Height: 470},
		Layout:   VBox{Margins: Margins{Left: 16, Top: 14, Right: 16, Bottom: 12}, Spacing: 8},
		Children: []Widget{
			// Two-column form: labels on the left, inputs on the right.
			Composite{
				Layout: Grid{Columns: 2, Spacing: 8, MarginsZero: true},
				Children: []Widget{
					Label{Text: "API Key", Alignment: AlignHNearVCenter},
					LineEdit{AssignTo: &keyEdit, CueBanner: keyCue},

					Label{Text: "Watch Folder", Alignment: AlignHNearVCenter},
					Composite{
						Layout: HBox{MarginsZero: true, Spacing: 6},
						Children: []Widget{
							LineEdit{AssignTo: &folderEdit, Text: initFolder, CueBanner: `C:\SCC\Reports`},
							PushButton{Text: "Browse…", MaxSize: Size{Width: 90}, OnClicked: browse},
						},
					},

					Label{Text: "API Base URL", Alignment: AlignHNearVCenter},
					LineEdit{AssignTo: &urlEdit, Text: initURL},
				},
			},
			Label{Text: "Files to upload (matched in the watch folder). Add or remove as needed:"},
			Composite{
				Layout: HBox{MarginsZero: true, Spacing: 6},
				Children: []Widget{
					TableView{
						AssignTo:            &filesTV,
						ColumnsOrderable:    false,
						LastColumnStretched: true,
						MinSize:             Size{Height: 150},
						Columns:             []TableViewColumn{{Title: "File"}},
						Model:               filesModel,
					},
					Composite{
						Layout:    VBox{MarginsZero: true, Spacing: 6},
						Alignment: AlignHNearVNear,
						MaxSize:   Size{Width: 100},
						Children: []Widget{
							PushButton{Text: "Add…", MinSize: Size{Width: 90}, OnClicked: addFile},
							PushButton{Text: "Remove", MinSize: Size{Width: 90}, OnClicked: removeFile},
							PushButton{Text: "Refresh", MinSize: Size{Width: 90}, OnClicked: refresh},
						},
					},
				},
			},
			VSpacer{}, // push the action bar to the bottom
			Composite{
				Layout: HBox{MarginsZero: true},
				Children: []Widget{
					Label{AssignTo: &status, Text: "Requires administrator (elevated automatically)."},
					HSpacer{},
					PushButton{AssignTo: &actionBtn, Text: btnText, MinSize: Size{Width: 130}, OnClicked: apply},
				},
			},
		},
	}).Run()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	return 0
}
