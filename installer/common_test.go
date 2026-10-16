package main

import (
	"archive/zip"
	"bytes"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestGUID(t *testing.T) {
	g := mustGUID("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}")
	if g.Data1 != 0xB4BFCC3A || g.Data2 != 0xDB2C || g.Data3 != 0x424C || g.Data4 != [8]byte{0xB0, 0x29, 0x7F, 0xE9, 0x9A, 0x87, 0xC6, 0x41} {
		t.Fatalf("wrong guid %+v", g)
	}
	s := mustGUID("{00021401-0000-0000-C000-000000000046}")
	if s.Data1 != 0x00021401 || s.Data4 != [8]byte{0xC0, 0, 0, 0, 0, 0, 0, 0x46} {
		t.Fatalf("wrong guid %+v", s)
	}
}

func TestZipSlip(t *testing.T) {
	var buf bytes.Buffer
	w := zip.NewWriter(&buf)
	f, _ := w.Create("../evil.txt")
	f.Write([]byte("x"))
	w.Close()
	r, _ := zip.NewReader(bytes.NewReader(buf.Bytes()), int64(buf.Len()))
	if err := extractZip(r, "", t.TempDir()); err == nil {
		t.Fatal("a path leaving the folder was accepted")
	}
	var buf2 bytes.Buffer
	w = zip.NewWriter(&buf2)
	f, _ = w.Create("tools/../../evil.txt")
	f.Write([]byte("x"))
	w.Close()
	r, _ = zip.NewReader(bytes.NewReader(buf2.Bytes()), int64(buf2.Len()))
	if err := extractZip(r, "tools/", t.TempDir()); err == nil {
		t.Fatal("a path leaving the folder was accepted (with prefix)")
	}
}

func TestContentRange(t *testing.T) {
	for in, want := range map[string][2]int64{"bytes 100-199/1234": {100, 1234}, "bytes */500": {0, 500}, " bytes 0-0/1 ": {0, 1}} {
		s, tot, ok := contentRange(in)
		if !ok || s != want[0] || tot != want[1] {
			t.Fatalf("%q: got %d %d %v", in, s, tot, ok)
		}
	}
	if _, _, ok := contentRange("nonsense"); ok {
		t.Fatal("accepted nonsense")
	}
}

func TestWindowArgs(t *testing.T) {
	a := strings.Join(appWindowArgs("http://127.0.0.1:1/", `C:\Users\A B\AppData\Local\RAX Surgicals Outreach\window`, 10, 20, 780, 660), "|")
	for _, want := range []string{"--app=http://127.0.0.1:1/", `--user-data-dir=C:\Users\A B\AppData\Local\RAX Surgicals Outreach\window`, "--no-first-run",
		"--disable-extensions", "--disable-features=Translate", "--window-size=780,660", "--window-position=10,20"} {
		if !strings.Contains(a, want) {
			t.Fatalf("missing %s in %s", want, a)
		}
	}
	if x, y, w, h := fitWindow(1360, 880, 0, 0, 1280, 680); w != 1248 || h != 648 || x != 16 || y != 16 {
		t.Fatalf("fit on a small screen: %d %d %d %d", x, y, w, h)
	}
	if x, y, w, h := fitWindow(780, 660, 0, 0, 1920, 1040); w != 780 || h != 660 || x != 570 || y != 190 {
		t.Fatalf("centred: %d %d %d %d", x, y, w, h)
	}
	if x, y, _, _ := fitWindow(780, 660, 0, 0, 0, 0); x != -1 || y != -1 {
		t.Fatal("no screen size: no position")
	}
}

// a server that serves data, stops sending in the middle of the first answer, and answers range requests
func flakyServer(t *testing.T, data []byte, stallAt int, ranges bool) (*httptest.Server, *int32) {
	var calls int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		n := atomic.AddInt32(&calls, 1)
		start := 0
		if rg := r.Header.Get("Range"); rg != "" && ranges {
			start, _ = strconv.Atoi(strings.TrimSuffix(strings.TrimPrefix(rg, "bytes="), "-"))
			w.Header().Set("Content-Range", fmt.Sprintf("bytes %d-%d/%d", start, len(data)-1, len(data)))
			w.Header().Set("Content-Length", strconv.Itoa(len(data)-start))
			w.WriteHeader(http.StatusPartialContent)
		} else {
			w.Header().Set("Content-Length", strconv.Itoa(len(data)))
			w.WriteHeader(http.StatusOK)
		}
		body := data[start:]
		if n == 1 && stallAt > 0 {
			w.Write(body[:stallAt])
			w.(http.Flusher).Flush()
			select { // stop sending, as a stuck line does
			case <-r.Context().Done():
			case <-time.After(5 * time.Second):
			}
			return
		}
		w.Write(body)
	}))
	return srv, &calls
}

func testData(n int) []byte {
	b := make([]byte, n)
	for i := range b {
		b[i] = byte(i * 7)
	}
	return b
}

func TestDownloadResumesAfterStall(t *testing.T) {
	old := stallAfter
	stallAfter = 400 * time.Millisecond
	defer func() { stallAfter = old }()
	data := testData(300_000)
	srv, calls := flakyServer(t, data, 120_000, true)
	defer srv.Close()
	var lines []string
	p, err := download(srv.URL+"/python.zip", func(f float64, s string) { lines = append(lines, s) })
	if err != nil {
		t.Fatal(err)
	}
	defer os.Remove(p)
	got, _ := os.ReadFile(p)
	if !bytes.Equal(got, data) {
		t.Fatalf("file differs: %d bytes", len(got))
	}
	if *calls != 2 {
		t.Fatalf("expected one reconnect, got %d requests", *calls)
	}
	if !strings.Contains(strings.Join(lines, "\n"), "continuing") {
		t.Fatal("the user was not told that the download continues")
	}
}

func TestDownloadRestartsWithoutRanges(t *testing.T) {
	old := stallAfter
	stallAfter = 400 * time.Millisecond
	defer func() { stallAfter = old }()
	data := testData(200_000)
	srv, calls := flakyServer(t, data, 50_000, false)
	defer srv.Close()
	p, err := download(srv.URL+"/python.zip", func(float64, string) {})
	if err != nil {
		t.Fatal(err)
	}
	defer os.Remove(p)
	got, _ := os.ReadFile(p)
	if !bytes.Equal(got, data) || *calls != 2 {
		t.Fatalf("file %d bytes, %d requests", len(got), *calls)
	}
}

func TestDownloadGivesUpOnMissingFile(t *testing.T) {
	srv := httptest.NewServer(http.NotFoundHandler())
	defer srv.Close()
	start := time.Now()
	if _, err := download(srv.URL+"/python.zip", func(float64, string) {}); err == nil || time.Since(start) > 3*time.Second {
		t.Fatalf("a missing file should fail at once: %v", err)
	}
}

func runtimePackage(t *testing.T, prefix string) []byte {
	var buf bytes.Buffer
	w := zip.NewWriter(&buf)
	for _, n := range []string{"pythonw", "python313.dll", "Lib/os.py"} {
		f, _ := w.Create(prefix + n)
		f.Write([]byte("x"))
	}
	f, _ := w.Create("python.nuspec")
	f.Write([]byte("<package/>"))
	w.Close()
	return buf.Bytes()
}

func TestUnpackNuGetLayout(t *testing.T) {
	t.Setenv("RAX_TEST_HOME", t.TempDir())
	pkg := filepath.Join(t.TempDir(), "python.3.13.3.nupkg")
	os.WriteFile(pkg, runtimePackage(t, "tools/"), 0o644)
	if err := unpackRuntime(pkg); err != nil {
		t.Fatal(err)
	}
	if !fileExists(filepath.Join(runtimeDir(), "pythonw")) || !fileExists(filepath.Join(runtimeDir(), "Lib", "os.py")) || fileExists(filepath.Join(runtimeDir(), "python.nuspec")) {
		t.Fatal("NuGet package not unpacked from its tools folder")
	}
	bad := filepath.Join(t.TempDir(), "python-3.13.3-embed-amd64.zip")
	os.WriteFile(bad, runtimePackage(t, "other/"), 0o644)
	if err := unpackRuntime(bad); err == nil {
		t.Fatal("a package without Python was accepted")
	}
}

// An update from RAX Outreach 2.1: the data and the downloaded Python move to the new folders, the rest goes.
func TestMoveLegacy(t *testing.T) {
	home := t.TempDir()
	t.Setenv("RAX_TEST_HOME", home)
	write := func(p, s string) {
		os.MkdirAll(filepath.Dir(p), 0o755)
		if err := os.WriteFile(p, []byte(s), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	oldData := filepath.Join(home, "LocalAppData", "RAX Outreach", "data")
	write(filepath.Join(oldData, "outreach.db"), "db")
	write(filepath.Join(oldData, "files", "catalogue.pdf"), "pdf")
	write(filepath.Join(oldData, "backups", "2026-10-14.db"), "backup")
	write(filepath.Join(home, "LocalAppData", "RAX Outreach", "window", "Default", "Preferences"), "{}")
	oldProg := filepath.Join(home, "LocalAppData", "Programs", "RAX Outreach")
	write(filepath.Join(oldProg, "program", "start.py"), "")
	write(filepath.Join(oldProg, "runtime", pythonwName), "python")
	write(filepath.Join(oldProg, "RAX Outreach"), "old launcher")
	for _, p := range []string{filepath.Join(home, "Programs", "RAX Outreach.lnk"), filepath.Join(home, "Desktop", "RAX Outreach.lnk")} {
		write(p, "old icon")
	}
	regSetString(runKey, legacyName, `"old" --background`)
	if !hasLegacy() {
		t.Fatal("the old install was not found")
	}

	to, err := moveLegacyData()
	if err != nil || to != dataDir() {
		t.Fatalf("data not moved: %q %v", to, err)
	}
	newData := filepath.Join(home, "LocalAppData", "RAX Surgicals Outreach", "data")
	for _, f := range []string{"outreach.db", filepath.Join("files", "catalogue.pdf"), filepath.Join("backups", "2026-10-14.db")} {
		if !fileExists(filepath.Join(newData, f)) {
			t.Fatalf("%s missing after the move", f)
		}
	}
	if !fileExists(filepath.Join(appWindowProfile(), "Default", "Preferences")) {
		t.Fatal("the window profile did not move along")
	}
	if dirExists(filepath.Join(home, "LocalAppData", "RAX Outreach")) {
		t.Fatal("the old data folder is still there")
	}
	removeLegacyEntries()
	if fileExists(filepath.Join(home, "Programs", "RAX Outreach.lnk")) || fileExists(filepath.Join(home, "Desktop", "RAX Outreach.lnk")) {
		t.Fatal("old icons left")
	}
	if v, _ := regGetString(runKey, legacyName); v != "" {
		t.Fatal("old start-with-Windows entry left")
	}
	if !moveLegacyRuntime() || !runtimeReady() {
		t.Fatal("the old Python was not taken over")
	}
	removeLegacyProgram()
	if dirExists(oldProg) {
		t.Fatal("old program folder left")
	}
	if to, err := moveLegacyData(); to != "" || err != nil {
		t.Fatalf("a second run should find nothing to move: %q %v", to, err)
	}
}

// Data in both places: the new folder is the one in use and nothing is moved over it. An empty new folder does not count.
func TestMoveLegacyKeepsNewData(t *testing.T) {
	home := t.TempDir()
	t.Setenv("RAX_TEST_HOME", home)
	oldDB := filepath.Join(home, "LocalAppData", "RAX Outreach", "data", "outreach.db")
	os.MkdirAll(filepath.Dir(oldDB), 0o755)
	os.WriteFile(oldDB, []byte("old"), 0o644)
	os.MkdirAll(dataDir(), 0o755) // empty
	if to, err := moveLegacyData(); to == "" || err != nil {
		t.Fatalf("an empty new folder should be replaced: %q %v", to, err)
	}
	os.MkdirAll(filepath.Dir(oldDB), 0o755)
	os.WriteFile(oldDB, []byte("older copy"), 0o644)
	if to, err := moveLegacyData(); to != "" || err != nil {
		t.Fatalf("moved over data in use: %q %v", to, err)
	}
	if b, _ := os.ReadFile(filepath.Join(dataDir(), "outreach.db")); string(b) != "old" {
		t.Fatalf("the data in use changed: %q", b)
	}
	if !fileExists(oldDB) {
		t.Fatal("the other copy should be left as it is")
	}
}
