// RAX Surgicals Outreach for Windows: one program that is both the setup and the installed app's launcher.
//
//	RAX-Surgicals-Outreach-Setup.exe            shows the setup window and installs for the current Windows user
//	RAX Surgicals Outreach.exe (installed copy) starts the app (or opens its window if it already runs)
//	RAX Surgicals Outreach.exe --background     starts the app without a window (used when starting with Windows)
//	RAX Surgicals Outreach.exe --uninstall      removes the app (Windows Settings > Apps calls this)
package main

import (
	"os"
	"path/filepath"
	"strings"
)

const (
	appName    = "RAX Surgicals Outreach"
	slogan     = "Find buyers. Email them. Turn replies into orders."
	appVersion = "1.0"
	publisher  = "RAX Surgicals"
	appPort    = 8765
	runKey     = `Software\Microsoft\Windows\CurrentVersion\Run`

	// Up to version 2.1 the app was called RAX Outreach. An update moves its data and removes the rest (see migrate.go).
	// Two names stay as they were, because Windows and running copies know the app by them: the key of its entry in
	// Settings > Apps, and the name the running app answers with on /api/me.
	legacyName = "RAX Outreach"
	uninstKey  = `Software\Microsoft\Windows\CurrentVersion\Uninstall\RAX Outreach`
	appID      = "RAX Outreach"
)

func main() {
	args := os.Args[1:]
	switch {
	case hasArg(args, "--finish-uninstall"):
		finishUninstall(hasArg(args, "--delete-data"))
	case hasArg(args, "--uninstall"):
		uninstall()
	case hasArg(args, "--setup") || !isInstalledCopy():
		runSetup()
	default:
		launch(hasArg(args, "--background"))
	}
}

func hasArg(args []string, name string) bool {
	for _, a := range args {
		if strings.EqualFold(a, name) {
			return true
		}
	}
	return false
}

// Where things live. Everything is per user, so no administrator rights are needed.
func installDir() string   { return filepath.Join(localAppData(), "Programs", appName) }
func dataRoot() string     { return filepath.Join(localAppData(), appName) }
func dataDir() string      { return filepath.Join(dataRoot(), "data") }
func programDir() string   { return filepath.Join(installDir(), "program") }
func runtimeDir() string   { return filepath.Join(installDir(), "runtime") }
func launcherPath() string { return filepath.Join(installDir(), appName+exeSuffix) }
func iconPath() string     { return filepath.Join(installDir(), "rax.ico") }

// The folders of version 2.1 and earlier (RAX Outreach), emptied and removed by an update.
func legacyInstallDir() string { return filepath.Join(localAppData(), "Programs", legacyName) }
func legacyDataRoot() string   { return filepath.Join(localAppData(), legacyName) }

func selfPath() string {
	p, err := os.Executable()
	if err != nil {
		return os.Args[0]
	}
	if r, err := filepath.EvalSymlinks(p); err == nil {
		p = r
	}
	return p
}

// The installed copy sits in the install folder next to the program files.
func isInstalledCopy() bool {
	return samePath(filepath.Dir(selfPath()), installDir()) && fileExists(filepath.Join(programDir(), "start.py"))
}

func samePath(a, b string) bool {
	return strings.EqualFold(filepath.Clean(a), filepath.Clean(b))
}

func fileExists(p string) bool {
	st, err := os.Stat(p)
	return err == nil && !st.IsDir()
}

func dirExists(p string) bool {
	st, err := os.Stat(p)
	return err == nil && st.IsDir()
}
