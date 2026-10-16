package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

var localClient = &http.Client{Timeout: 4 * time.Second, Transport: &http.Transport{Proxy: nil}} // never through a proxy: this is this PC

// appRunning reports whether the app (this version or an earlier one) answers on its port.
func appRunning() bool {
	resp, err := localClient.Get(fmt.Sprintf("http://127.0.0.1:%d/api/me", appPort))
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	var me struct {
		App string `json:"app"`
	}
	b, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<16))
	return json.Unmarshal(b, &me) == nil && me.App == appID
}

func portFree() bool {
	l, err := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", appPort))
	if err != nil {
		return false
	}
	l.Close()
	return true
}

// stopRunningApp asks a running copy to stop (with the token it left in its data folder: the new one, or that of
// RAX Outreach 2.1 and earlier), waits for it, and as a last resort ends the processes that run from the install
// folders.
func stopRunningApp() {
	if appRunning() {
		for _, dir := range []string{dataDir(), filepath.Join(legacyDataRoot(), "data")} {
			tok, err := os.ReadFile(filepath.Join(dir, "stop.token"))
			if err != nil {
				continue
			}
			req, _ := http.NewRequest("POST", fmt.Sprintf("http://127.0.0.1:%d/api/shutdown", appPort), strings.NewReader("{}"))
			req.Header.Set("Content-Type", "application/json")
			req.Header.Set("X-Requested-With", "rax")
			req.Header.Set("X-RAX-Stop", strings.TrimSpace(string(tok)))
			if resp, err := localClient.Do(req); err == nil {
				resp.Body.Close()
				if resp.StatusCode == http.StatusOK {
					break
				}
			}
		}
		for i := 0; i < 40 && appRunning(); i++ {
			time.Sleep(250 * time.Millisecond)
		}
	}
	killProcessesIn(installDir())
	killProcessesIn(legacyInstallDir())
	closeAppWindows()
	time.Sleep(300 * time.Millisecond)
}

func copyFile(src, dst string, mode os.FileMode) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		return err
	}
	tmp := dst + ".new"
	out, err := os.OpenFile(tmp, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, mode)
	if err != nil {
		return err
	}
	if _, err := io.Copy(out, in); err != nil {
		out.Close()
		os.Remove(tmp)
		return err
	}
	if err := out.Close(); err != nil {
		os.Remove(tmp)
		return err
	}
	return retry(func() error { os.Remove(dst); return os.Rename(tmp, dst) })
}

// retry repeats a file operation for a moment: antivirus programs often hold new files open briefly.
func retry(fn func() error) error {
	var err error
	for i := 0; i < 8; i++ {
		if err = fn(); err == nil {
			return nil
		}
		retrySleep(i)
	}
	return err
}

func retrySleep(i int) { time.Sleep(time.Duration(150*(i+1)) * time.Millisecond) }

func dirSizeKB(dir string) uint32 {
	var total int64
	filepath.Walk(dir, func(_ string, info os.FileInfo, err error) error {
		if err == nil && !info.IsDir() {
			total += info.Size()
		}
		return nil
	})
	return uint32(total / 1024)
}

// guid is the Windows GUID layout.
type guid struct {
	Data1 uint32
	Data2 uint16
	Data3 uint16
	Data4 [8]byte
}

// mustGUID parses "{XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}".
func mustGUID(s string) *guid {
	h := strings.NewReplacer("{", "", "}", "", "-", "").Replace(s)
	if len(h) != 32 {
		panic("bad guid " + s)
	}
	var b [16]byte
	for i := 0; i < 16; i++ {
		var v byte
		for _, c := range h[2*i : 2*i+2] {
			v <<= 4
			switch {
			case c >= '0' && c <= '9':
				v |= byte(c - '0')
			case c >= 'a' && c <= 'f':
				v |= byte(c-'a') + 10
			case c >= 'A' && c <= 'F':
				v |= byte(c-'A') + 10
			default:
				panic("bad guid " + s)
			}
		}
		b[i] = v
	}
	g := &guid{
		Data1: uint32(b[0])<<24 | uint32(b[1])<<16 | uint32(b[2])<<8 | uint32(b[3]),
		Data2: uint16(b[4])<<8 | uint16(b[5]),
		Data3: uint16(b[6])<<8 | uint16(b[7]),
	}
	copy(g.Data4[:], b[8:])
	return g
}
