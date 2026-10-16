package main

// Version 2.2 renamed RAX Outreach to RAX Surgicals Outreach, and with it its folders, icons and start-with-Windows
// entry. An update from 2.1 or earlier moves the data and the Python it downloaded into the new folders, so nothing
// is lost or downloaded again, and removes what is left under the old name.
//
// The order matters. The data moves first, right after the old copy has stopped: if that fails, nothing else has
// changed and Try again starts over. The old icons and start-with-Windows entry go at the same time, so the old
// version (now without its data) cannot be started by mistake while setup continues. The old program folder goes
// last, once the new one is complete.

import (
	"os"
	"path/filepath"
)

// hasLegacy reports whether anything of RAX Outreach 2.1 or earlier is on this PC.
func hasLegacy() bool {
	return dirExists(legacyInstallDir()) || dirExists(filepath.Join(legacyDataRoot(), "data"))
}

// moveLegacyData moves the old data folder (leads, emails, settings, files, backups) to the new place.
// It reports where the data is now, or "" when there was nothing to move.
func moveLegacyData() (string, error) {
	from, to := filepath.Join(legacyDataRoot(), "data"), dataDir()
	if !dirExists(from) {
		return "", nil
	}
	if dirExists(to) {
		if !emptyDir(to) {
			return "", nil // both exist: the new folder is the one in use, and the old one is left as it is
		}
		os.Remove(to)
	}
	if err := os.MkdirAll(dataRoot(), 0o755); err != nil {
		return "", err
	}
	if err := retry(func() error { return os.Rename(from, to) }); err != nil {
		return "", err
	}
	// The old window's browser profile only remembers the window's size and place: it moves along if it can.
	if old := filepath.Join(legacyDataRoot(), "window"); dirExists(old) {
		if dirExists(appWindowProfile()) || os.Rename(old, appWindowProfile()) != nil {
			os.RemoveAll(old)
		}
	}
	os.Remove(legacyDataRoot()) // only removes it when nothing else is left in it
	return to, nil
}

// moveLegacyRuntime takes over the Python that the old version downloaded, so it is not downloaded again.
func moveLegacyRuntime() bool {
	old := filepath.Join(legacyInstallDir(), "runtime")
	if runtimeReady() || !fileExists(filepath.Join(old, pythonwName)) {
		return false
	}
	if os.MkdirAll(installDir(), 0o755) != nil {
		return false
	}
	os.RemoveAll(runtimeDir())
	return retry(func() error { return os.Rename(old, runtimeDir()) }) == nil
}

// removeLegacyEntries removes the old icons (Start menu, desktop, Startup folder) and start-with-Windows entry.
func removeLegacyEntries() {
	removeShortcutsNamed(legacyName)
	regDeleteValue(runKey, legacyName)
}

// removeLegacyProgram deletes the old program folder. Whatever is still in use stays until the next update.
func removeLegacyProgram() {
	old := legacyInstallDir()
	for i := 0; i < 8 && dirExists(old); i++ {
		if os.RemoveAll(old) == nil {
			break
		}
		retrySleep(i)
	}
}

func emptyDir(p string) bool {
	f, err := os.Open(p)
	if err != nil {
		return false
	}
	defer f.Close()
	names, _ := f.Readdirnames(1)
	return len(names) == 0
}
