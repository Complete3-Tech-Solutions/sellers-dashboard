//go:build windows

package main

import (
	"fmt"
	"os"
	"strings"

	"github.com/lxn/walk"
	. "github.com/lxn/walk/declarative"

	"github.com/complete3tech/scc-agent/internal/config"
	"github.com/complete3tech/scc-agent/internal/creds"
	"github.com/complete3tech/scc-agent/internal/service"
	"github.com/complete3tech/scc-agent/internal/version"
)

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

	var (
		mw         *walk.MainWindow
		keyEdit    *walk.LineEdit
		folderEdit *walk.LineEdit
		urlEdit    *walk.LineEdit
		status     *walk.Label
		actionBtn  *walk.PushButton
	)

	browse := func() {
		dlg := &walk.FileDialog{Title: "Select the folder of job-cost Excel files"}
		if ok, err := dlg.ShowBrowseFolder(mw); err == nil && ok {
			folderEdit.SetText(dlg.FilePath)
		}
	}

	apply := func() {
		actionBtn.SetEnabled(false)
		status.SetText("Working…")
		err := applySettings(
			strings.TrimSpace(keyEdit.Text()),
			strings.TrimSpace(folderEdit.Text()),
			strings.TrimSpace(urlEdit.Text()),
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
		Size:     Size{Width: 560, Height: 250},
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
