package main

// The windows of RAX Surgicals Outreach (setup and the app) are Edge or Chrome in app mode. They run on a browser profile of their
// own, never the visitor's normal one: extensions installed in the normal browser (translators, AI helpers, ad
// blockers) would otherwise add their buttons and boxes to these windows, and an already open browser would ignore
// the window size.

import (
	"fmt"
	"os"
	"path/filepath"
)

// appWindowProfile is the browser profile of the app's window. The launcher hands it to start.py.
func appWindowProfile() string { return filepath.Join(dataRoot(), "window") }

// legacyWindowProfile is the window's profile in RAX Outreach 2.1.
func legacyWindowProfile() string { return filepath.Join(legacyDataRoot(), "window") }

// setupWindowProfile is a separate, temporary profile for the setup window, so that closing setup never holds up
// the app window that opens right after it.
func setupWindowProfile() string { return filepath.Join(os.TempDir(), appName+" Setup window") }

// appWindowArgs are the browser options for one window of the app or setup. x and y below 0 leave the position to the browser.
func appWindowArgs(url, profile string, x, y, w, h int) []string {
	args := []string{
		"--app=" + url,
		"--user-data-dir=" + profile,
		"--no-first-run",
		"--no-default-browser-check",
		"--disable-extensions",
		"--disable-sync",
		"--disable-features=Translate",
		"--hide-crash-restore-bubble",
	}
	if w > 0 && h > 0 {
		args = append(args, fmt.Sprintf("--window-size=%d,%d", w, h))
	}
	if x >= 0 && y >= 0 {
		args = append(args, fmt.Sprintf("--window-position=%d,%d", x, y))
	}
	return args
}

// fitWindow keeps a window of w x h inside the screen's free area (ax, ay, aw, ah, in the browser's units) and
// centres it there. Without a known area it returns no position.
func fitWindow(w, h, ax, ay, aw, ah int) (x, y, fw, fh int) {
	if aw <= 0 || ah <= 0 {
		return -1, -1, w, h
	}
	const margin = 32
	if w > aw-margin {
		w = aw - margin
	}
	if h > ah-margin {
		h = ah - margin
	}
	return ax + (aw-w)/2, ay + (ah-h)/2, w, h
}

// removeWindowProfiles deletes the window profiles (uninstall). A profile still in use stays until the next time.
func removeWindowProfiles() {
	for _, p := range []string{appWindowProfile(), setupWindowProfile(), legacyWindowProfile()} {
		for i := 0; i < 12; i++ {
			if os.RemoveAll(p) == nil {
				break
			}
			if _, err := os.Stat(p); os.IsNotExist(err) {
				break
			}
			retrySleep(i)
		}
	}
}
