//go:build !windows

package main

// Stand-ins used to test setup, launch and uninstall on Linux: everything goes under $RAX_TEST_HOME.

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
)

const (
	exeSuffix   = ""
	pythonwName = "pythonw"
)

func testHome() string {
	if h := os.Getenv("RAX_TEST_HOME"); h != "" {
		return h
	}
	return filepath.Join(os.TempDir(), "rax-test-home")
}

func localAppData() string { return filepath.Join(testHome(), "LocalAppData") }
func desktopDir() string   { return filepath.Join(testHome(), "Desktop") }
func programsDir() string  { return filepath.Join(testHome(), "Programs") }
func startupDir() string   { return filepath.Join(testHome(), "Startup") }
func downloadsDir() string { return filepath.Join(testHome(), "Downloads") }

var regMu sync.Mutex

func regFile() string { return filepath.Join(testHome(), "registry.json") }

func regLoad() map[string]map[string]any {
	m := map[string]map[string]any{}
	if b, err := os.ReadFile(regFile()); err == nil {
		json.Unmarshal(b, &m)
	}
	return m
}

func regSave(m map[string]map[string]any) error {
	os.MkdirAll(testHome(), 0o755)
	b, _ := json.MarshalIndent(m, "", "  ")
	return os.WriteFile(regFile(), b, 0o644)
}

func regGetString(path, name string) (string, error) {
	regMu.Lock()
	defer regMu.Unlock()
	if v, ok := regLoad()[path][name].(string); ok {
		return v, nil
	}
	return "", os.ErrNotExist
}

func regSet(path, name string, v any) error {
	regMu.Lock()
	defer regMu.Unlock()
	m := regLoad()
	if m[path] == nil {
		m[path] = map[string]any{}
	}
	m[path][name] = v
	return regSave(m)
}

func regSetString(path, name, value string) error       { return regSet(path, name, value) }
func regSetDWORD(path, name string, value uint32) error { return regSet(path, name, value) }

func regDeleteValue(path, name string) error {
	regMu.Lock()
	defer regMu.Unlock()
	m := regLoad()
	delete(m[path], name)
	return regSave(m)
}

func regDeleteTree(path string) error {
	regMu.Lock()
	defer regMu.Unlock()
	m := regLoad()
	delete(m, path)
	return regSave(m)
}

func shortcutPaths(name string) (startMenu, desktop, startup string) {
	return filepath.Join(programsDir(), name+".lnk"), filepath.Join(desktopDir(), name+".lnk"), filepath.Join(startupDir(), name+".lnk")
}

// makeShortcuts writes stand-in icons: target, icon and description, one per line.
func makeShortcuts(desktop bool) error {
	menu, desk, startup := shortcutPaths(appName)
	write := func(p string) error {
		os.MkdirAll(filepath.Dir(p), 0o755)
		return os.WriteFile(p, []byte(launcherPath()+"\n"+iconPath()+"\n"+slogan+"\n"), 0o644)
	}
	if err := write(menu); err != nil {
		return err
	}
	if desktop {
		if err := write(desk); err != nil {
			return err
		}
	} else {
		os.Remove(desk)
	}
	os.Remove(startup)
	return nil
}

func removeShortcutsNamed(name string) {
	menu, desk, startup := shortcutPaths(name)
	os.Remove(menu)
	os.Remove(desk)
	os.Remove(startup)
}

func removeShortcuts() {
	removeShortcutsNamed(appName)
	removeShortcutsNamed(legacyName)
}

func note(kind, text string) {
	fmt.Println(kind+":", text)
	os.MkdirAll(testHome(), 0o755)
	f, err := os.OpenFile(filepath.Join(testHome(), "messages.txt"), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err == nil {
		fmt.Fprintf(f, "%s: %s\n---\n", kind, text)
		f.Close()
	}
}

func showError(text string) { note("ERROR", text) }
func showInfo(text string)  { note("INFO", text) }

// Answers come from RAX_TEST_ANSWERS, e.g. "yes,no".
var answerIdx int

func askYesNo(text string, defaultYes bool) bool {
	ans := strings.Split(os.Getenv("RAX_TEST_ANSWERS"), ",")
	a := defaultYes
	if answerIdx < len(ans) && ans[answerIdx] != "" {
		a = ans[answerIdx] == "yes"
	}
	answerIdx++
	note("ASK", fmt.Sprintf("%s -> %v", text, a))
	return a
}

func startHidden(exe string, args []string, dir string, env []string) error {
	cmd := exec.Command(exe, args...)
	cmd.Dir, cmd.Env = dir, env
	f, _ := os.OpenFile(filepath.Join(testHome(), "app-output.txt"), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	cmd.Stdout, cmd.Stderr = f, f
	if err := cmd.Start(); err != nil {
		return err
	}
	go cmd.Wait()
	return nil
}

func startDetached(exe string, args []string, dir string) error {
	cmd := exec.Command(exe, args...)
	cmd.Dir = dir
	cmd.Env = os.Environ()
	if err := cmd.Start(); err != nil {
		return err
	}
	go cmd.Wait()
	return nil
}

// openAppWindow records the browser options it would use, on a 1366 x 728 work area.
func openAppWindow(url string, w, h int) bool {
	os.MkdirAll(testHome(), 0o755)
	f, err := os.OpenFile(filepath.Join(testHome(), "opened.txt"), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return false
	}
	x, y, w, h := fitWindow(w, h, 0, 0, 1366, 728)
	fmt.Fprintf(f, "%s\n", strings.Join(appWindowArgs(url, setupWindowProfile(), x, y, w, h), " "))
	f.Close()
	return true
}

func killProcessesIn(dir string) {}

// closeAppWindows records which windows would be closed: those on the app's profile and on that of 2.1.
func closeAppWindows() {
	os.MkdirAll(testHome(), 0o755)
	if f, err := os.OpenFile(filepath.Join(testHome(), "closed.txt"), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644); err == nil {
		fmt.Fprintln(f, appWindowProfile())
		fmt.Fprintln(f, legacyWindowProfile())
		f.Close()
	}
}

func findSystemPython() string {
	if os.Getenv("RAX_TEST_NO_SYSTEM_PYTHON") != "" {
		return ""
	}
	p, _ := exec.LookPath("python3")
	return p
}

func deleteSelfLater() { os.Remove(selfPath()) }
