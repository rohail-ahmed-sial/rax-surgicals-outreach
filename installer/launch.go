package main

import (
	"fmt"
	"os"
	"path/filepath"
	"time"
)

// launch starts the app (it opens its own window), or only opens the window when the app already runs.
func launch(background bool) {
	py := pythonExe()
	if py == "" {
		showError(appName + " is not completely installed: its Python runtime is missing.\n\nRun RAX-Surgicals-Outreach-Setup.exe again to repair it. Your data is kept.")
		return
	}
	args := []string{filepath.Join(programDir(), "start.py")}
	if background {
		args = append(args, "--no-browser")
	} else {
		args = append(args, "--window")
	}
	os.MkdirAll(dataDir(), 0o755)
	env := append(os.Environ(), "RAX_DATA_DIR="+dataDir(), "RAX_WINDOW_PROFILE="+appWindowProfile(), "RAX_LAUNCHER="+launcherPath(), "PYTHONUTF8=1")
	if err := startHidden(py, args, programDir(), env); err != nil {
		showError(appName + " could not start: " + err.Error())
	}
}

// uninstall removes the app; the data folder is kept unless the user chooses to delete it too.
func uninstall() {
	if !askYesNo("Remove "+appName+" from this computer?", false) {
		return
	}
	stopRunningApp()
	deleteData := askYesNo("Also delete your "+appName+" data?\n\nThis removes your leads, emails, settings and backups in:\n"+dataRoot()+
		"\n\nChoose No to keep them, for example to install "+appName+" again later.", false)
	removeShortcuts()
	regDeleteValue(runKey, appName)
	regDeleteValue(runKey, legacyName)
	regDeleteTree(uninstKey)
	removeLegacyProgram()
	// A program cannot delete the folder it runs from, so a temporary copy finishes the job.
	tmp := filepath.Join(os.TempDir(), fmt.Sprintf("rax-surgicals-outreach-uninstall-%d%s", time.Now().UnixNano(), exeSuffix))
	if err := copyFile(selfPath(), tmp, 0o755); err != nil {
		os.RemoveAll(installDir()) // try in place; whatever is in use stays behind
		removeWindowProfiles()
		showInfo(appName + " was removed.")
		return
	}
	args := []string{"--finish-uninstall"}
	if deleteData {
		args = append(args, "--delete-data")
	}
	if err := startDetached(tmp, args, os.TempDir()); err != nil {
		os.RemoveAll(installDir())
		removeWindowProfiles()
		showInfo(appName + " was removed.")
	}
}

func finishUninstall(deleteData bool) {
	dir := installDir() // always the known folder, never a path given on the command line
	for i := 0; i < 60; i++ {
		os.RemoveAll(dir)
		if _, err := os.Stat(dir); os.IsNotExist(err) {
			break
		}
		time.Sleep(250 * time.Millisecond)
	}
	if deleteData {
		os.RemoveAll(dataRoot())
		os.RemoveAll(legacyDataRoot()) // data that an update could not move (it found data in both places)
	}
	removeWindowProfiles() // the windows' browser profiles are not data: they always go
	showInfo(appName + " was removed from this computer.")
	deleteSelfLater()
}
