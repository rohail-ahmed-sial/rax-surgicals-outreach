package main

// Setup: a small page in its own window guides the install. The page talks to this program over 127.0.0.1.

import (
	"embed"
	"encoding/json"
	"fmt"
	"io/fs"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

//go:embed all:payload
var payload embed.FS

//go:embed assets
var assets embed.FS

type step struct {
	Key    string `json:"key"`
	Label  string `json:"label"`
	State  string `json:"state"` // wait, run, done, fail, skip
	Detail string `json:"detail"`
}

type setupState struct {
	mu        sync.Mutex
	State     string  `json:"state"` // idle, running, done, error
	Steps     []*step `json:"steps"`
	Progress  float64 `json:"progress"`
	Error     string  `json:"error"`
	lastSeen  time.Time
	opened    bool
	installed bool
}

var st = &setupState{State: "idle", lastSeen: time.Now()}

func newSteps(legacy bool) []*step {
	running := appName
	if legacy {
		running = legacyName // the version being updated still has its old name
	}
	steps := []*step{{Key: "stop", Label: "Closing " + running + " if it is open", State: "wait"}}
	if legacy {
		steps = append(steps, &step{Key: "move", Label: "Moving your data from " + legacyName, State: "wait"})
	}
	return append(steps,
		&step{Key: "files", Label: "Copying " + appName, State: "wait"},
		&step{Key: "python", Label: "Getting the Python runtime ready", State: "wait"},
		&step{Key: "icons", Label: "Adding the icons", State: "wait"},
		&step{Key: "windows", Label: "Registering with Windows", State: "wait"},
	)
}

func (s *setupState) set(key, state, detail string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, x := range s.Steps {
		if x.Key == key {
			x.State, x.Detail = state, detail
		}
	}
}

type options struct {
	Desktop   bool `json:"desktop"`
	Autostart bool `json:"autostart"`
}

func installedVersion() string {
	v, _ := regGetString(uninstKey, "DisplayVersion")
	if v == "" && (fileExists(filepath.Join(programDir(), "start.py")) || fileExists(filepath.Join(legacyInstallDir(), "program", "start.py"))) {
		v = "earlier"
	}
	return v
}

func runSetup() {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		showError("Setup could not start: " + err.Error())
		return
	}
	mux := http.NewServeMux()
	sub, _ := fs.Sub(assets, "assets")
	mux.Handle("/assets/", http.StripPrefix("/assets/", http.FileServer(http.FS(sub))))
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/" {
			http.NotFound(w, r)
			return
		}
		b, _ := assets.ReadFile("assets/setup.html")
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.Header().Set("Cache-Control", "no-store")
		w.Write(b)
	})
	mux.HandleFunc("/api/info", func(w http.ResponseWriter, r *http.Request) {
		st.mu.Lock()
		st.lastSeen = time.Now()
		st.mu.Unlock()
		auto, _ := regGetString(runKey, appName)
		if auto == "" {
			auto, _ = regGetString(runKey, legacyName)
		}
		prev := installedVersion()
		writeJSON(w, map[string]any{
			"version": appVersion, "installedVersion": prev, "installDir": installDir(), "dataDir": dataRoot(),
			"autostart": auto != "" || prev == "", "runtimeReady": runtimeReady() || fileExists(filepath.Join(legacyInstallDir(), "runtime", pythonwName)),
			"legacy": hasLegacy(), "legacyName": legacyName,
		})
	})
	mux.HandleFunc("/api/status", func(w http.ResponseWriter, r *http.Request) {
		st.mu.Lock()
		st.lastSeen = time.Now()
		b, _ := json.Marshal(st)
		st.mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Cache-Control", "no-store")
		w.Write(b)
	})
	mux.HandleFunc("/api/install", func(w http.ResponseWriter, r *http.Request) {
		if !sameOrigin(r) {
			http.Error(w, "bad request", 400)
			return
		}
		var o options
		json.NewDecoder(r.Body).Decode(&o)
		st.mu.Lock()
		if st.State == "running" {
			st.mu.Unlock()
			writeJSON(w, map[string]any{"ok": false})
			return
		}
		st.State, st.Error, st.Progress, st.Steps = "running", "", 0, newSteps(hasLegacy())
		st.mu.Unlock()
		go install(o)
		writeJSON(w, map[string]any{"ok": true})
	})
	mux.HandleFunc("/api/open", func(w http.ResponseWriter, r *http.Request) {
		if !sameOrigin(r) {
			http.Error(w, "bad request", 400)
			return
		}
		st.mu.Lock()
		st.opened = true
		st.mu.Unlock()
		err := startDetached(launcherPath(), nil, installDir())
		writeJSON(w, map[string]any{"ok": err == nil})
		go func() { time.Sleep(1500 * time.Millisecond); exitSetup() }()
	})
	mux.HandleFunc("/api/close", func(w http.ResponseWriter, r *http.Request) {
		if !sameOrigin(r) {
			http.Error(w, "bad request", 400)
			return
		}
		writeJSON(w, map[string]any{"ok": true})
		go func() { time.Sleep(300 * time.Millisecond); exitSetup() }()
	})
	url := fmt.Sprintf("http://%s/", ln.Addr().String())
	setupURL = url
	go func() {
		time.Sleep(200 * time.Millisecond)
		if !openAppWindow(url, 780, 660) {
			showError("Setup could not open its window. Open this address in your browser:\n\n" + url)
		}
	}()
	// Setup closes itself a while after its window is closed (the page asks for news every second while open).
	go func() {
		for {
			time.Sleep(2 * time.Second)
			st.mu.Lock()
			idle, running := time.Since(st.lastSeen), st.State == "running"
			st.mu.Unlock()
			if !running && idle > 45*time.Second {
				exitSetup()
			}
		}
	}()
	http.Serve(ln, mux)
}

var setupURL string

// exitSetup ends setup and removes the setup window's temporary browser profile once that window has closed.
func exitSetup() {
	p := setupWindowProfile()
	for i := 0; i < 16; i++ {
		if os.RemoveAll(p) == nil {
			break
		}
		time.Sleep(250 * time.Millisecond)
	}
	os.Exit(0)
}

// Requests that change something must come from the setup page itself.
func sameOrigin(r *http.Request) bool {
	if r.Method != "POST" {
		return false
	}
	o := r.Header.Get("Origin")
	return o == "" || strings.TrimSuffix(setupURL, "/") == o
}

func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	json.NewEncoder(w).Encode(v)
}

func fail(key, msg string) {
	st.set(key, "fail", msg)
	st.mu.Lock()
	st.State, st.Error = "error", msg
	st.mu.Unlock()
}

func install(o options) {
	// 1. a running copy holds its files open
	st.set("stop", "run", "")
	if appRunning() {
		stopRunningApp()
		if appRunning() {
			fail("stop", "It is still running. Close it with the power button in its menu, then press Try again.")
			return
		}
		st.set("stop", "done", "")
	} else {
		killProcessesIn(installDir())
		killProcessesIn(legacyInstallDir())
		closeAppWindows() // a window left from an earlier run, showing "stopped"
		st.set("stop", "skip", "It was not open")
	}

	// 2. RAX Outreach 2.1 or earlier: its data moves to the new folder, its icons and start-with-Windows entry go
	keptPython := false
	if hasLegacy() {
		st.set("move", "run", "")
		to, err := moveLegacyData()
		if err != nil {
			fail("move", "Could not move your data from "+filepath.Join(legacyDataRoot(), "data")+" to "+dataDir()+" ("+err.Error()+
				"). Nothing was changed. Close every "+legacyName+" window and press Try again.")
			return
		}
		removeLegacyEntries()
		keptPython = moveLegacyRuntime()
		if to != "" {
			st.set("move", "done", "Now in "+to)
		} else {
			st.set("move", "skip", "No data to move")
		}
	}

	// 3. program files (data lives elsewhere and is never touched)
	st.set("files", "run", "")
	if err := copyProgram(); err != nil {
		fail("files", "Could not copy the files: "+err.Error())
		return
	}
	st.set("files", "done", installDir())

	// 4. Python
	st.set("python", "run", "")
	if runtimeReady() {
		if keptPython {
			st.set("python", "done", "Kept from "+legacyName+", nothing downloaded")
		} else {
			st.set("python", "done", "Already there")
		}
	} else {
		how, err := prepareRuntime(func(f float64, d string) {
			st.mu.Lock()
			st.Progress = f
			st.mu.Unlock()
			st.set("python", "run", d)
		})
		st.mu.Lock()
		st.Progress = 0
		st.mu.Unlock()
		if err != nil {
			if p, err2 := useSystemPython(); err2 == nil {
				st.set("python", "done", "Using the Python already on this PC ("+p+")")
			} else {
				fail("python", "Python could not be downloaded ("+err.Error()+"). Check the internet connection and press Try again. "+
					"Or download "+manualRuntimeURL+" in your browser, put the file in the same folder as "+filepath.Base(selfPath())+" or in Downloads, and press Try again.")
				return
			}
		} else {
			st.set("python", "done", how)
		}
	}

	// 5. icons
	st.set("icons", "run", "")
	if err := makeShortcuts(o.Desktop); err != nil {
		fail("icons", "Could not add the icons: "+err.Error())
		return
	}
	if o.Desktop {
		st.set("icons", "done", "Start menu and desktop")
	} else {
		st.set("icons", "done", "Start menu")
	}

	// 6. Apps list and start with Windows
	st.set("windows", "run", "")
	if err := registerApp(); err != nil {
		fail("windows", "Could not register the app: "+err.Error())
		return
	}
	if o.Autostart {
		regSetString(runKey, appName, `"`+launcherPath()+`" --background`)
	} else {
		regDeleteValue(runKey, appName)
	}
	detail := "Listed in Settings > Apps"
	if o.Autostart {
		detail += ", starts with Windows"
	}
	st.set("windows", "done", detail)

	// the old program folder goes last, once the new one is complete
	removeLegacyEntries()
	removeLegacyProgram()

	st.mu.Lock()
	st.State, st.installed = "done", true
	st.mu.Unlock()
}

// copyProgram replaces the program files with the ones inside this setup, and copies this program as the launcher.
func copyProgram() error {
	if err := os.MkdirAll(installDir(), 0o755); err != nil {
		return err
	}
	tmp := programDir() + ".new"
	os.RemoveAll(tmp)
	err := fs.WalkDir(payload, "payload", func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel := strings.TrimPrefix(strings.TrimPrefix(p, "payload"), "/")
		if rel == "" {
			return nil
		}
		var target string
		switch {
		case rel == "program" || strings.HasPrefix(rel, "program/"):
			target = filepath.Join(tmp, filepath.FromSlash(strings.TrimPrefix(strings.TrimPrefix(rel, "program"), "/")))
		default:
			target = filepath.Join(installDir(), filepath.FromSlash(rel))
		}
		if d.IsDir() {
			return os.MkdirAll(target, 0o755)
		}
		b, err := payload.ReadFile(p)
		if err != nil {
			return err
		}
		if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
			return err
		}
		return os.WriteFile(target, b, 0o644)
	})
	if err != nil {
		os.RemoveAll(tmp)
		return err
	}
	if err := retry(func() error {
		if err := os.RemoveAll(programDir()); err != nil {
			return err
		}
		return os.Rename(tmp, programDir())
	}); err != nil {
		return err
	}
	if !samePath(selfPath(), launcherPath()) {
		if err := copyFile(selfPath(), launcherPath(), 0o755); err != nil {
			return err
		}
	}
	return os.MkdirAll(dataDir(), 0o755)
}

func registerApp() error {
	vals := map[string]string{
		"DisplayName":          appName,
		"DisplayVersion":       appVersion,
		"Publisher":            publisher,
		"DisplayIcon":          iconPath(),
		"InstallLocation":      installDir(),
		"UninstallString":      `"` + launcherPath() + `" --uninstall`,
		"QuietUninstallString": `"` + launcherPath() + `" --uninstall`,
		"InstallDate":          time.Now().Format("20060102"),
		"Comments":             slogan,
	}
	for k, v := range vals {
		if err := regSetString(uninstKey, k, v); err != nil {
			return err
		}
	}
	regSetDWORD(uninstKey, "NoModify", 1)
	regSetDWORD(uninstKey, "NoRepair", 1)
	regSetDWORD(uninstKey, "EstimatedSize", dirSizeKB(installDir()))
	return nil
}
