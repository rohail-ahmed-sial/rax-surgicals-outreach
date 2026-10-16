package main

// The Python runtime the app runs on. Setup puts Python into the install folder, so nothing needs to be installed by
// hand and nothing else on the PC changes. In order:
//  1. a Python package that is already on this PC, next to the setup file or in Downloads (no internet needed);
//  2. the official "embeddable" Python from python.org;
//  3. the same Python from NuGet (Microsoft's package server, another network), if python.org is slow or blocked;
//  4. a Python 3.9+ that is already installed on the PC.
// A download that stops for a while continues where it stopped instead of waiting or starting again.

import (
	"archive/zip"
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"
)

// Official Windows x64 Python packages, newest first; the next one is tried when one fails. NuGet packages keep
// Python in their "tools" folder.
var runtimeURLs = []string{
	"https://www.python.org/ftp/python/3.13.3/python-3.13.3-embed-amd64.zip",
	"https://api.nuget.org/v3-flatcontainer/python/3.13.3/python.3.13.3.nupkg",
	"https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip",
	"https://api.nuget.org/v3-flatcontainer/python/3.12.10/python.3.12.10.nupkg",
	"https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip",
}

// manualRuntimeURL is the file a user can download in the browser and put next to the setup file.
const manualRuntimeURL = "https://www.python.org/ftp/python/3.13.3/python-3.13.3-embed-amd64.zip"

const pythonPathFile = "python-path.txt" // in the install folder, when a Python already on the PC is used

var (
	stallAfter  = 20 * time.Second // no data for this long: drop the connection and continue where it stopped
	maxIdleRuns = 3                // connections in a row that bring no data before the next source is tried
	maxPerURL   = 30 * time.Minute // a source that is still not done after this long is given up
)

func init() { // tests use a short wait
	if ms, err := strconv.Atoi(os.Getenv("RAX_TEST_STALL_MS")); err == nil && ms > 0 {
		stallAfter = time.Duration(ms) * time.Millisecond
	}
}

// pythonExe returns the Python that runs the app, or "" when there is none.
func pythonExe() string {
	if p := filepath.Join(runtimeDir(), pythonwName); fileExists(p) {
		return p
	}
	if b, err := os.ReadFile(filepath.Join(installDir(), pythonPathFile)); err == nil {
		if p := strings.TrimSpace(string(b)); p != "" && fileExists(p) {
			return p
		}
	}
	return ""
}

func runtimeReady() bool { return fileExists(filepath.Join(runtimeDir(), pythonwName)) }

// archivePrefix is the folder inside a package that holds Python: NuGet packages use "tools/".
func archivePrefix(name string) string {
	if strings.HasSuffix(strings.ToLower(name), ".nupkg") {
		return "tools/"
	}
	return ""
}

func sourceName(u string) string {
	if p, err := url.Parse(u); err == nil && p.Host != "" {
		h := strings.TrimPrefix(strings.ToLower(p.Hostname()), "www.")
		if strings.HasSuffix(h, "nuget.org") {
			return "nuget.org"
		}
		return h
	}
	return "the internet"
}

// localRuntime finds a Python package the user already downloaded: next to the setup file or in Downloads.
func localRuntime() []string {
	var found []string
	seen := map[string]bool{}
	for _, dir := range []string{filepath.Dir(selfPath()), downloadsDir()} {
		if dir == "" {
			continue
		}
		var names []string
		for _, pat := range []string{"python-3*-embed-amd64*.zip", "python.3*.nupkg"} {
			m, _ := filepath.Glob(filepath.Join(dir, pat))
			names = append(names, m...)
		}
		sort.Sort(sort.Reverse(sort.StringSlice(names))) // newer versions first
		for _, n := range names {
			if k := strings.ToLower(n); !seen[k] {
				seen[k] = true
				found = append(found, n)
			}
		}
	}
	return found
}

// prepareRuntime puts Python in place. report gets the share done (0 to 1, or below 0 when unknown) and a line to show.
func prepareRuntime(report func(float64, string)) (string, error) {
	for _, p := range localRuntime() {
		report(-1, "Using "+filepath.Base(p)+" from this computer")
		if err := unpackRuntime(p); err == nil {
			return "Python from " + filepath.Base(p), nil
		}
	}
	urls := runtimeURLs
	if u := os.Getenv("RAX_TEST_RUNTIME_URL"); u != "" {
		urls = strings.Fields(u)
	}
	var errs []string
	for _, u := range urls {
		tmp, err := download(u, report)
		if err == nil {
			report(-1, "Unpacking Python")
			err = unpackRuntime(tmp)
			os.Remove(tmp)
			if err == nil {
				return "Downloaded from " + sourceName(u), nil
			}
		}
		errs = append(errs, sourceName(u)+": "+err.Error())
	}
	if len(errs) == 0 {
		errs = append(errs, "no download address")
	}
	return "", errors.New(strings.Join(dedupe(errs), "; "))
}

func dedupe(list []string) []string {
	var out []string
	seen := map[string]bool{}
	for _, s := range list {
		if !seen[s] {
			seen[s] = true
			out = append(out, s)
		}
	}
	return out
}

var dlClient = &http.Client{Transport: &http.Transport{
	Proxy:                 http.ProxyFromEnvironment,
	DialContext:           (&net.Dialer{Timeout: 20 * time.Second, KeepAlive: 30 * time.Second}).DialContext,
	TLSHandshakeTimeout:   20 * time.Second,
	ResponseHeaderTimeout: 30 * time.Second,
	ForceAttemptHTTP2:     true,
}}

var errGone = errors.New("not available there")

// download fetches one package into a temporary file. When the connection stops sending, it reconnects and asks for
// the rest only (HTTP range), so a slow or unsteady line still gets there.
func download(u string, report func(float64, string)) (string, error) {
	f, err := os.CreateTemp("", "rax-python-*"+filepath.Ext(u))
	if err != nil {
		return "", err
	}
	name := f.Name()
	fail := func(e error) (string, error) { f.Close(); os.Remove(name); return "", e }
	var got, total int64 = 0, -1
	sp := newSpeed()
	src := sourceName(u)
	show := func(pos int64, note string) {
		frac := -1.0
		if total > 0 {
			frac = float64(pos) / float64(total)
		}
		line := "Downloading Python from " + src + ": " + sizeText(pos, total)
		if rate := sp.rate(); rate > 0 {
			line += " · " + rateText(rate)
			if total > 0 && pos < total {
				line += " · " + leftText(float64(total-pos)/rate)
			}
		}
		if note != "" {
			line += " · " + note
		}
		report(frac, line)
	}
	show(0, "")
	began, idle, try := time.Now(), 0, 0
	for {
		try++
		before := got
		var last time.Time
		n, size, restarted, err := fetchFrom(u, f, got, func(pos, size int64) {
			if size > 0 {
				total = size
			}
			sp.add(pos)
			if time.Since(last) > 250*time.Millisecond {
				last = time.Now()
				show(pos, "")
			}
		})
		if restarted {
			got, before = 0, 0
		}
		got += n
		if size > 0 {
			total = size
		}
		if err == nil && (total < 0 || got == total) {
			break
		}
		if err == nil && got > total {
			if terr := f.Truncate(0); terr != nil {
				return fail(terr)
			}
			got, before = 0, -1
			err = errors.New("the file was larger than announced")
		}
		if errors.Is(err, errGone) {
			return fail(err)
		}
		if got > before {
			idle = 0
		} else {
			idle++
		}
		if idle >= maxIdleRuns || time.Since(began) > maxPerURL {
			return fail(friendly(err))
		}
		show(got, fmt.Sprintf("the connection stopped, continuing (try %d)", try+1))
		time.Sleep(time.Duration(min(try, 5)) * time.Second)
	}
	if err := f.Close(); err != nil {
		os.Remove(name)
		return "", err
	}
	show(got, "")
	return name, nil
}

// fetchFrom writes the file from offset on. It returns the bytes written, the full size when known, whether the
// server sent the whole file again (it did not take the range, so the file was emptied first), and the error.
func fetchFrom(u string, f *os.File, offset int64, progress func(pos, size int64)) (written, total int64, restarted bool, err error) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, "GET", u, nil)
	if err != nil {
		return 0, -1, false, err
	}
	req.Header.Set("User-Agent", "RAX-Surgicals-Outreach-Setup/"+appVersion)
	if offset > 0 {
		req.Header.Set("Range", fmt.Sprintf("bytes=%d-", offset))
	}
	resp, err := dlClient.Do(req)
	if err != nil {
		return 0, -1, false, err
	}
	defer resp.Body.Close()
	total = -1
	switch {
	case resp.StatusCode == http.StatusPartialContent && offset > 0:
		start, size, ok := contentRange(resp.Header.Get("Content-Range"))
		if !ok || start != offset {
			return 0, -1, false, errors.New("the server sent the wrong part of the file")
		}
		total = size
	case resp.StatusCode == http.StatusOK:
		if offset > 0 { // the server sends the whole file again
			if err := f.Truncate(0); err != nil {
				return 0, -1, false, err
			}
			offset, restarted = 0, true
		}
		total = resp.ContentLength
	case resp.StatusCode == http.StatusRequestedRangeNotSatisfiable && offset > 0:
		if _, size, ok := contentRange(resp.Header.Get("Content-Range")); ok && size == offset {
			return 0, size, false, nil // everything was already there
		}
		if err := f.Truncate(0); err != nil {
			return 0, -1, false, err
		}
		return 0, -1, true, errors.New("the download had to start again")
	case resp.StatusCode == http.StatusNotFound || resp.StatusCode == http.StatusGone || resp.StatusCode == http.StatusForbidden:
		return 0, -1, false, fmt.Errorf("%w (%s)", errGone, resp.Status)
	default:
		return 0, -1, false, fmt.Errorf("the server answered %s", resp.Status)
	}
	if _, err := f.Seek(offset, io.SeekStart); err != nil {
		return 0, total, restarted, err
	}
	watchdog := time.AfterFunc(stallAfter, cancel) // no data for a while: give up this connection
	defer watchdog.Stop()
	buf := make([]byte, 64*1024)
	for {
		n, rerr := resp.Body.Read(buf)
		if n > 0 {
			watchdog.Reset(stallAfter)
			if _, werr := f.Write(buf[:n]); werr != nil {
				return written, total, restarted, werr
			}
			written += int64(n)
			progress(offset+written, total)
		}
		if rerr == io.EOF {
			return written, total, restarted, nil
		}
		if rerr != nil {
			if ctx.Err() != nil {
				rerr = errors.New("no data arrived for " + strconv.Itoa(int(stallAfter.Seconds())) + " seconds")
			}
			return written, total, restarted, rerr
		}
	}
}

// contentRange reads "bytes 100-199/1234".
func contentRange(h string) (start, total int64, ok bool) {
	h = strings.TrimSpace(strings.TrimPrefix(strings.TrimSpace(h), "bytes"))
	slash := strings.LastIndexByte(h, '/')
	if slash < 0 {
		return 0, 0, false
	}
	t, err := strconv.ParseInt(strings.TrimSpace(h[slash+1:]), 10, 64)
	if err != nil {
		return 0, 0, false
	}
	r := strings.TrimSpace(h[:slash])
	if r == "*" {
		return 0, t, true
	}
	dash := strings.IndexByte(r, '-')
	if dash < 0 {
		return 0, 0, false
	}
	s, err := strconv.ParseInt(strings.TrimSpace(r[:dash]), 10, 64)
	if err != nil {
		return 0, 0, false
	}
	return s, t, true
}

func friendly(err error) error {
	if err == nil {
		return errors.New("the download did not finish")
	}
	var ne net.Error
	if errors.As(err, &ne) && ne.Timeout() {
		return errors.New("the server did not answer in time")
	}
	msg := err.Error()
	if strings.Contains(msg, "no such host") {
		return errors.New("no internet connection (the address could not be found)")
	}
	return err
}

// speed keeps the last few seconds of progress to show the current download speed.
type speed struct {
	t []time.Time
	n []int64
}

func newSpeed() *speed { return &speed{} }

func (s *speed) add(total int64) {
	now := time.Now()
	if len(s.n) > 0 && total < s.n[len(s.n)-1] {
		s.t, s.n = nil, nil
	}
	s.t, s.n = append(s.t, now), append(s.n, total)
	for len(s.t) > 2 && now.Sub(s.t[0]) > 4*time.Second {
		s.t, s.n = s.t[1:], s.n[1:]
	}
}

// rate is bytes per second over the last seconds, or 0 when not known yet.
func (s *speed) rate() float64 {
	if len(s.t) < 2 {
		return 0
	}
	dt := s.t[len(s.t)-1].Sub(s.t[0]).Seconds()
	if dt < 0.5 {
		return 0
	}
	return float64(s.n[len(s.n)-1]-s.n[0]) / dt
}

func sizeText(got, total int64) string {
	if total > 0 {
		return fmt.Sprintf("%.1f of %.1f MB", float64(got)/1e6, float64(total)/1e6)
	}
	return fmt.Sprintf("%.1f MB", float64(got)/1e6)
}

func rateText(bps float64) string {
	if bps >= 1e6 {
		return fmt.Sprintf("%.1f MB/s", bps/1e6)
	}
	return fmt.Sprintf("%.0f KB/s", bps/1e3)
}

func leftText(sec float64) string {
	switch {
	case sec < 10:
		return "a few seconds left"
	case sec < 60:
		return fmt.Sprintf("about %d s left", int(sec/5+0.5)*5)
	case sec < 3600:
		return fmt.Sprintf("about %d min left", int(sec/60+0.5))
	default:
		return "over an hour left"
	}
}

// unpackRuntime checks the package holds a Python runtime and puts it in place of the old one.
func unpackRuntime(pkg string) error {
	zr, err := zip.OpenReader(pkg)
	if err != nil {
		return fmt.Errorf("the file is not a valid package: %w", err)
	}
	defer zr.Close()
	prefix := archivePrefix(pkg)
	hasExe, hasLib := false, false
	for _, f := range zr.File {
		name := strings.ToLower(f.Name)
		if !strings.HasPrefix(name, prefix) {
			continue
		}
		name = strings.TrimPrefix(name, prefix)
		if name == strings.ToLower(pythonwName) {
			hasExe = true
		}
		if !strings.Contains(name, "/") && strings.HasPrefix(name, "python3") && (strings.HasSuffix(name, ".dll") || strings.HasSuffix(name, ".zip")) {
			hasLib = true
		}
	}
	if !hasExe || !hasLib {
		return errors.New("the package does not contain Python for Windows")
	}
	tmpDir := runtimeDir() + ".new"
	os.RemoveAll(tmpDir)
	if err := extractZip(&zr.Reader, prefix, tmpDir); err != nil {
		os.RemoveAll(tmpDir)
		return err
	}
	if err := retry(func() error {
		if err := os.RemoveAll(runtimeDir()); err != nil {
			return err
		}
		return os.Rename(tmpDir, runtimeDir())
	}); err != nil {
		os.RemoveAll(tmpDir)
		return err
	}
	os.Remove(filepath.Join(installDir(), pythonPathFile))
	return nil
}

// extractZip unpacks the entries under prefix (without the prefix) into dest, refusing paths that leave dest.
func extractZip(zr *zip.Reader, prefix, dest string) error {
	if err := os.MkdirAll(dest, 0o755); err != nil {
		return err
	}
	for _, f := range zr.File {
		if !strings.HasPrefix(strings.ToLower(f.Name), prefix) {
			continue
		}
		rel := f.Name[len(prefix):]
		if rel == "" {
			continue
		}
		target := filepath.Join(dest, filepath.FromSlash(rel))
		r, err := filepath.Rel(dest, target)
		if err != nil || r == ".." || strings.HasPrefix(r, ".."+string(filepath.Separator)) || filepath.IsAbs(rel) {
			return fmt.Errorf("unsafe path in package: %s", f.Name)
		}
		if f.FileInfo().IsDir() || strings.HasSuffix(rel, "/") {
			if err := os.MkdirAll(target, 0o755); err != nil {
				return err
			}
			continue
		}
		if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
			return err
		}
		rc, err := f.Open()
		if err != nil {
			return err
		}
		mode := os.FileMode(0o644)
		if f.Mode()&0o111 != 0 {
			mode = 0o755
		}
		out, err := os.OpenFile(target, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, mode)
		if err != nil {
			rc.Close()
			return err
		}
		_, err = io.Copy(out, rc)
		rc.Close()
		if cerr := out.Close(); err == nil {
			err = cerr
		}
		if err != nil {
			return err
		}
	}
	return nil
}

// useSystemPython remembers a Python 3.9+ that is already installed on this PC (the last resort).
func useSystemPython() (string, error) {
	p := findSystemPython()
	if p == "" {
		return "", errors.New("no Python 3.9 or newer found on this PC")
	}
	if err := os.WriteFile(filepath.Join(installDir(), pythonPathFile), []byte(p), 0o644); err != nil {
		return "", err
	}
	return p, nil
}
