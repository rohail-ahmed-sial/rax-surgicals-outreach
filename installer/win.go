//go:build windows

package main

// Windows parts: known folders, registry, shortcuts, message boxes, starting and stopping processes.
// Only standard Windows DLLs are called (kernel32, user32, shell32, ole32, advapi32).

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

const (
	exeSuffix   = ".exe"
	pythonwName = "pythonw.exe"

	createNoWindow = 0x08000000
	hkcu           = 0x80000001
	keyAllAccess   = 0xF003F
	keyRead        = 0x20019
	regSZ          = 1
	regDWORD       = 4
)

var (
	kernel32 = syscall.NewLazyDLL("kernel32.dll")
	user32   = syscall.NewLazyDLL("user32.dll")
	shell32  = syscall.NewLazyDLL("shell32.dll")
	ole32    = syscall.NewLazyDLL("ole32.dll")
	advapi32 = syscall.NewLazyDLL("advapi32.dll")

	procMessageBoxW                = user32.NewProc("MessageBoxW")
	procShellExecuteW              = shell32.NewProc("ShellExecuteW")
	procSHGetKnownFolderPath       = shell32.NewProc("SHGetKnownFolderPath")
	procCoInitializeEx             = ole32.NewProc("CoInitializeEx")
	procCoUninitialize             = ole32.NewProc("CoUninitialize")
	procCoCreateInstance           = ole32.NewProc("CoCreateInstance")
	procCoTaskMemFree              = ole32.NewProc("CoTaskMemFree")
	procRegCreateKeyExW            = advapi32.NewProc("RegCreateKeyExW")
	procRegSetValueExW             = advapi32.NewProc("RegSetValueExW")
	procRegDeleteValueW            = advapi32.NewProc("RegDeleteValueW")
	procRegDeleteTreeW             = advapi32.NewProc("RegDeleteTreeW")
	procRegDeleteKeyW              = advapi32.NewProc("RegDeleteKeyW")
	procQueryFullProcessImageNameW = kernel32.NewProc("QueryFullProcessImageNameW")
	procSystemParametersInfoW      = user32.NewProc("SystemParametersInfoW")
	procGetDpiForSystem            = user32.NewProc("GetDpiForSystem")
	procNtQueryInformationProcess  = syscall.NewLazyDLL("ntdll.dll").NewProc("NtQueryInformationProcess")
)

var (
	folderDesktop      = mustGUID("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}")
	folderPrograms     = mustGUID("{A77F5D77-2E2B-44C3-A6A2-ABA601054A51}")
	folderStartup      = mustGUID("{B97D20BB-F46A-4C97-BA10-5E3608430854}")
	folderLocalAppData = mustGUID("{F1B32785-6FBA-4FCF-9D55-7B8E7F157091}")
	folderDownloads    = mustGUID("{374DE290-123F-4565-9164-39C4925E467B}")

	clsidShellLink = mustGUID("{00021401-0000-0000-C000-000000000046}")
	iidShellLinkW  = mustGUID("{000214F9-0000-0000-C000-000000000046}")
	iidPersistFile = mustGUID("{0000010B-0000-0000-C000-000000000046}")
)

func utf16p(s string) *uint16 {
	p, err := syscall.UTF16PtrFromString(s)
	if err != nil {
		p, _ = syscall.UTF16PtrFromString(strings.ReplaceAll(s, "\x00", ""))
	}
	return p
}

func utf16PtrToString(p *uint16) string {
	if p == nil {
		return ""
	}
	n := 0
	for ptr := unsafe.Pointer(p); *(*uint16)(ptr) != 0; n++ {
		ptr = unsafe.Add(ptr, 2)
	}
	return syscall.UTF16ToString(unsafe.Slice(p, n))
}

// ---------- folders ----------

func knownFolder(id *guid, fallback string) string {
	var p *uint16
	r, _, _ := procSHGetKnownFolderPath.Call(uintptr(unsafe.Pointer(id)), 0, 0, uintptr(unsafe.Pointer(&p)))
	if r == 0 && p != nil {
		s := utf16PtrToString(p)
		procCoTaskMemFree.Call(uintptr(unsafe.Pointer(p)))
		if s != "" {
			return s
		}
	}
	return fallback
}

func localAppData() string {
	fb := os.Getenv("LOCALAPPDATA")
	if fb == "" {
		fb = filepath.Join(os.Getenv("USERPROFILE"), "AppData", "Local")
	}
	return knownFolder(folderLocalAppData, fb)
}

func desktopDir() string {
	return knownFolder(folderDesktop, filepath.Join(os.Getenv("USERPROFILE"), "Desktop"))
}

func programsDir() string {
	return knownFolder(folderPrograms, filepath.Join(os.Getenv("APPDATA"), "Microsoft", "Windows", "Start Menu", "Programs"))
}

func downloadsDir() string {
	return knownFolder(folderDownloads, filepath.Join(os.Getenv("USERPROFILE"), "Downloads"))
}

func startupDir() string {
	return knownFolder(folderStartup, filepath.Join(os.Getenv("APPDATA"), "Microsoft", "Windows", "Start Menu", "Programs", "Startup"))
}

// ---------- registry (current user only) ----------

func regGetString(path, name string) (string, error) {
	var h syscall.Handle
	if err := syscall.RegOpenKeyEx(hkcu, utf16p(path), 0, keyRead, &h); err != nil {
		return "", err
	}
	defer syscall.RegCloseKey(h)
	var typ, size uint32
	if err := syscall.RegQueryValueEx(h, utf16p(name), nil, &typ, nil, &size); err != nil {
		return "", err
	}
	if size == 0 {
		return "", nil
	}
	buf := make([]uint16, size/2+1)
	if err := syscall.RegQueryValueEx(h, utf16p(name), nil, &typ, (*byte)(unsafe.Pointer(&buf[0])), &size); err != nil {
		return "", err
	}
	return syscall.UTF16ToString(buf), nil
}

func regCreate(path string) (syscall.Handle, error) {
	var h syscall.Handle
	r, _, _ := procRegCreateKeyExW.Call(hkcu, uintptr(unsafe.Pointer(utf16p(path))), 0, 0, 0, keyAllAccess, 0, uintptr(unsafe.Pointer(&h)), 0)
	if r != 0 {
		return 0, syscall.Errno(r)
	}
	return h, nil
}

func regSetString(path, name, value string) error {
	h, err := regCreate(path)
	if err != nil {
		return err
	}
	defer syscall.RegCloseKey(h)
	data, _ := syscall.UTF16FromString(value)
	r, _, _ := procRegSetValueExW.Call(uintptr(h), uintptr(unsafe.Pointer(utf16p(name))), 0, regSZ,
		uintptr(unsafe.Pointer(&data[0])), uintptr(len(data)*2))
	if r != 0 {
		return syscall.Errno(r)
	}
	return nil
}

func regSetDWORD(path, name string, value uint32) error {
	h, err := regCreate(path)
	if err != nil {
		return err
	}
	defer syscall.RegCloseKey(h)
	v := value
	r, _, _ := procRegSetValueExW.Call(uintptr(h), uintptr(unsafe.Pointer(utf16p(name))), 0, regDWORD,
		uintptr(unsafe.Pointer(&v)), 4)
	if r != 0 {
		return syscall.Errno(r)
	}
	return nil
}

func regDeleteValue(path, name string) error {
	var h syscall.Handle
	if err := syscall.RegOpenKeyEx(hkcu, utf16p(path), 0, keyAllAccess, &h); err != nil {
		return err
	}
	defer syscall.RegCloseKey(h)
	r, _, _ := procRegDeleteValueW.Call(uintptr(h), uintptr(unsafe.Pointer(utf16p(name))))
	if r != 0 {
		return syscall.Errno(r)
	}
	return nil
}

func regDeleteTree(path string) error {
	r, _, _ := procRegDeleteTreeW.Call(hkcu, uintptr(unsafe.Pointer(utf16p(path))))
	procRegDeleteKeyW.Call(hkcu, uintptr(unsafe.Pointer(utf16p(path)))) // the key itself, if it is still there
	if r != 0 && r != 2 {                                               // 2: not found
		return syscall.Errno(r)
	}
	return nil
}

// ---------- shortcuts ----------

// shortcutPaths are where an icon with this name can be: the Start menu, the desktop, and the Startup folder (the zip
// version's "start with Windows").
func shortcutPaths(name string) (startMenu, desktop, startup string) {
	return filepath.Join(programsDir(), name+".lnk"), filepath.Join(desktopDir(), name+".lnk"), filepath.Join(startupDir(), name+".lnk")
}

func makeShortcuts(desktop bool) error {
	target, work, icon := launcherPath(), installDir(), iconPath()
	menu, desk, startup := shortcutPaths(appName)
	if err := createShortcut(menu, target, "", work, icon, slogan); err != nil {
		return err
	}
	if desktop {
		if err := createShortcut(desk, target, "", work, icon, slogan); err != nil {
			return err
		}
	} else {
		os.Remove(desk)
	}
	os.Remove(startup) // it would start a second copy
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

func createShortcut(lnk, target, args, work, icon, desc string) error {
	os.MkdirAll(filepath.Dir(lnk), 0o755)
	err := createShortcutCOM(lnk, target, args, work, icon, desc)
	if err == nil && fileExists(lnk) {
		return nil
	}
	if err2 := createShortcutPS(lnk, target, args, work, icon, desc); err2 == nil && fileExists(lnk) {
		return nil
	} else if err == nil {
		err = err2
	}
	if err == nil {
		err = errors.New("the shortcut was not created")
	}
	return err
}

// comObj is a COM interface pointer: its first field points to the table of methods.
type comObj struct{ vtbl *[32]uintptr }

// comCall calls method `index` of a COM object. All pointers passed are to heap objects kept alive by the caller.
func comCall(obj *comObj, index int, args ...uintptr) uintptr {
	r, _, _ := syscall.SyscallN(obj.vtbl[index], append([]uintptr{uintptr(unsafe.Pointer(obj))}, args...)...)
	return r
}

func createShortcutCOM(lnk, target, args, work, icon, desc string) error {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	hr, _, _ := procCoInitializeEx.Call(0, 0x2) // COINIT_APARTMENTTHREADED
	if hr == 0 || hr == 1 {
		defer procCoUninitialize.Call()
	}
	var psl *comObj
	hr, _, _ = procCoCreateInstance.Call(uintptr(unsafe.Pointer(clsidShellLink)), 0, 1, uintptr(unsafe.Pointer(iidShellLinkW)), uintptr(unsafe.Pointer(&psl)))
	if int32(hr) < 0 || psl == nil {
		return fmt.Errorf("shell link not available (0x%08x)", uint32(hr))
	}
	defer comCall(psl, 2) // Release
	strs := []*uint16{utf16p(target), utf16p(args), utf16p(work), utf16p(desc), utf16p(icon), utf16p(lnk)}
	// IShellLinkW: SetDescription 7, SetWorkingDirectory 9, SetArguments 11, SetIconLocation 17, SetPath 20
	calls := []struct {
		idx  int
		args []uintptr
	}{
		{20, []uintptr{uintptr(unsafe.Pointer(strs[0]))}},
		{11, []uintptr{uintptr(unsafe.Pointer(strs[1]))}},
		{9, []uintptr{uintptr(unsafe.Pointer(strs[2]))}},
		{7, []uintptr{uintptr(unsafe.Pointer(strs[3]))}},
		{17, []uintptr{uintptr(unsafe.Pointer(strs[4])), 0}},
	}
	for _, c := range calls {
		if hr := comCall(psl, c.idx, c.args...); int32(hr) < 0 {
			runtime.KeepAlive(strs)
			return fmt.Errorf("shell link method %d failed (0x%08x)", c.idx, uint32(hr))
		}
	}
	var ppf *comObj
	if hr := comCall(psl, 0, uintptr(unsafe.Pointer(iidPersistFile)), uintptr(unsafe.Pointer(&ppf))); int32(hr) < 0 || ppf == nil {
		return fmt.Errorf("persist file not available (0x%08x)", uint32(hr))
	}
	defer comCall(ppf, 2)
	hr = comCall(ppf, 6, uintptr(unsafe.Pointer(strs[5])), 1) // IPersistFile::Save(path, TRUE)
	runtime.KeepAlive(strs)
	if int32(hr) < 0 {
		return fmt.Errorf("saving the shortcut failed (0x%08x)", uint32(hr))
	}
	return nil
}

func createShortcutPS(lnk, target, args, work, icon, desc string) error {
	q := func(s string) string { return "'" + strings.ReplaceAll(s, "'", "''") + "'" }
	script := fmt.Sprintf("$s=(New-Object -ComObject WScript.Shell).CreateShortcut(%s);$s.TargetPath=%s;$s.Arguments=%s;$s.WorkingDirectory=%s;$s.IconLocation=%s;$s.Description=%s;$s.Save()",
		q(lnk), q(target), q(args), q(work), q(icon+",0"), q(desc))
	cmd := exec.Command("powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: createNoWindow}
	return runWithTimeout(cmd, 60*time.Second)
}

func runWithTimeout(cmd *exec.Cmd, d time.Duration) error {
	if err := cmd.Start(); err != nil {
		return err
	}
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	select {
	case err := <-done:
		return err
	case <-time.After(d):
		cmd.Process.Kill()
		return errors.New("timed out")
	}
}

// ---------- messages ----------

func messageBox(text string, flags uintptr) int {
	r, _, _ := procMessageBoxW.Call(0, uintptr(unsafe.Pointer(utf16p(text))), uintptr(unsafe.Pointer(utf16p(appName))), flags|0x10000) // MB_SETFOREGROUND
	return int(r)
}

func showError(text string) { messageBox(text, 0x10) }
func showInfo(text string)  { messageBox(text, 0x40) }

func askYesNo(text string, defaultYes bool) bool {
	flags := uintptr(0x4 | 0x20) // MB_YESNO | MB_ICONQUESTION
	if !defaultYes {
		flags |= 0x100 // MB_DEFBUTTON2
	}
	return messageBox(text, flags) == 6 // IDYES
}

// ---------- processes ----------

func startHidden(exe string, args []string, dir string, env []string) error {
	cmd := exec.Command(exe, args...)
	cmd.Dir, cmd.Env = dir, env
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: createNoWindow}
	if err := cmd.Start(); err != nil {
		return err
	}
	return cmd.Process.Release()
}

func startDetached(exe string, args []string, dir string) error {
	cmd := exec.Command(exe, args...)
	cmd.Dir = dir
	if err := cmd.Start(); err != nil {
		return err
	}
	return cmd.Process.Release()
}

func appBrowsers() []string {
	var found []string
	bases := []string{os.Getenv("ProgramFiles(x86)"), os.Getenv("ProgramFiles"), os.Getenv("LOCALAPPDATA")}
	for _, rel := range [][]string{{"Microsoft", "Edge", "Application", "msedge.exe"}, {"Google", "Chrome", "Application", "chrome.exe"}} {
		for _, b := range bases {
			if b == "" {
				continue
			}
			p := filepath.Join(append([]string{b}, rel...)...)
			if fileExists(p) {
				found = append(found, p)
			}
		}
	}
	return found
}

// workAreaDIP is the screen area outside the taskbar, in the units Edge and Chrome use for window sizes
// (1/96 inch). This program is DPI aware, so Windows reports real pixels; they are scaled back here.
func workAreaDIP() (x, y, w, h int) {
	var r struct{ Left, Top, Right, Bottom int32 }
	if ok, _, _ := procSystemParametersInfoW.Call(0x0030, 0, uintptr(unsafe.Pointer(&r)), 0); ok == 0 { // SPI_GETWORKAREA
		return 0, 0, 0, 0
	}
	dpi := int64(96)
	if procGetDpiForSystem.Find() == nil {
		if d, _, _ := procGetDpiForSystem.Call(); d >= 96 && d <= 960 {
			dpi = int64(d)
		}
	}
	s := func(v int32) int { return int(int64(v) * 96 / dpi) }
	return s(r.Left), s(r.Top), s(r.Right - r.Left), s(r.Bottom - r.Top)
}

// openAppWindow shows a page as its own window (Edge or Chrome app mode, on setup's own browser profile), centred,
// else in the default browser.
func openAppWindow(url string, w, h int) bool {
	ax, ay, aw, ah := workAreaDIP()
	x, y, w, h := fitWindow(w, h, ax, ay, aw, ah)
	for _, exe := range appBrowsers() {
		cmd := exec.Command(exe, appWindowArgs(url, setupWindowProfile(), x, y, w, h)...)
		if cmd.Start() == nil {
			cmd.Process.Release()
			return true
		}
	}
	r, _, _ := procShellExecuteW.Call(0, uintptr(unsafe.Pointer(utf16p("open"))), uintptr(unsafe.Pointer(utf16p(url))), 0, 0, 1)
	return r > 32
}

// processCommandLine reads another process's command line (Windows 8.1 and later).
func processCommandLine(h syscall.Handle) string {
	buf := make([]byte, 8192)
	for try := 0; try < 3; try++ {
		var need uint32
		r, _, _ := procNtQueryInformationProcess.Call(uintptr(h), 60, uintptr(unsafe.Pointer(&buf[0])), uintptr(len(buf)), uintptr(unsafe.Pointer(&need))) // ProcessCommandLineInformation
		if r == 0 {
			us := (*struct {
				Length, MaximumLength uint16
				_                     uint32
				Buffer                *uint16
			})(unsafe.Pointer(&buf[0]))
			if us.Buffer == nil || us.Length == 0 {
				return ""
			}
			return syscall.UTF16ToString(unsafe.Slice(us.Buffer, int(us.Length/2)))
		}
		if uint32(r) != 0xC0000004 || need <= uint32(len(buf)) { // STATUS_INFO_LENGTH_MISMATCH: try a larger buffer
			return ""
		}
		buf = make([]byte, need)
	}
	return ""
}

// closeAppWindows closes the app's windows (update and uninstall): the Edge or Chrome processes that run on the app's
// own browser profile, or on that of RAX Outreach 2.1. Browsers on any other profile are never touched.
func closeAppWindows() {
	markers := []string{strings.ToLower(filepath.Clean(appWindowProfile())), strings.ToLower(filepath.Clean(legacyWindowProfile()))}
	snap, err := syscall.CreateToolhelp32Snapshot(0x2, 0) // TH32CS_SNAPPROCESS
	if err != nil {
		return
	}
	defer syscall.CloseHandle(snap)
	var pe syscall.ProcessEntry32
	pe.Size = uint32(unsafe.Sizeof(pe))
	for err := syscall.Process32First(snap, &pe); err == nil; err = syscall.Process32Next(snap, &pe) {
		name := strings.ToLower(syscall.UTF16ToString(pe.ExeFile[:]))
		if name != "msedge.exe" && name != "chrome.exe" {
			continue
		}
		h, err := syscall.OpenProcess(0x1000|0x0001, false, pe.ProcessID) // QUERY_LIMITED_INFORMATION | TERMINATE
		if err != nil {
			continue
		}
		cmd := strings.ToLower(processCommandLine(h))
		for _, m := range markers {
			if strings.Contains(cmd, m) {
				syscall.TerminateProcess(h, 0)
				break
			}
		}
		syscall.CloseHandle(h)
	}
}

// killProcessesIn ends programs started from dir (the app's own Python), never anything else.
func killProcessesIn(dir string) {
	prefix := strings.ToLower(filepath.Clean(dir)) + string(filepath.Separator)
	snap, err := syscall.CreateToolhelp32Snapshot(0x2, 0) // TH32CS_SNAPPROCESS
	if err != nil {
		return
	}
	defer syscall.CloseHandle(snap)
	var pe syscall.ProcessEntry32
	pe.Size = uint32(unsafe.Sizeof(pe))
	self := uint32(os.Getpid())
	for err := syscall.Process32First(snap, &pe); err == nil; err = syscall.Process32Next(snap, &pe) {
		if pe.ProcessID == self || pe.ProcessID == 0 {
			continue
		}
		h, err := syscall.OpenProcess(0x1000|0x0001, false, pe.ProcessID) // QUERY_LIMITED_INFORMATION | TERMINATE
		if err != nil {
			continue
		}
		buf := make([]uint16, 1024)
		size := uint32(len(buf))
		r, _, _ := procQueryFullProcessImageNameW.Call(uintptr(h), 0, uintptr(unsafe.Pointer(&buf[0])), uintptr(unsafe.Pointer(&size)))
		if r != 0 {
			path := strings.ToLower(syscall.UTF16ToString(buf[:size]))
			if strings.HasPrefix(path, prefix) {
				syscall.TerminateProcess(h, 1)
			}
		}
		syscall.CloseHandle(h)
	}
}

// findSystemPython looks for an installed Python 3.9+ and prefers its windowless pythonw.exe.
func findSystemPython() string {
	for _, c := range [][]string{{"py", "-3"}, {"python"}, {"python3"}} {
		exe, err := exec.LookPath(c[0])
		if err != nil || strings.Contains(strings.ToLower(exe), `\windowsapps\`) && c[0] != "py" {
			continue // the Microsoft Store placeholder only opens the Store
		}
		cmd := exec.Command(exe, append(c[1:], "-c", "import sys;print(sys.executable);print(int(sys.version_info[:2]>=(3,9)))")...)
		cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: createNoWindow}
		var out strings.Builder
		cmd.Stdout = &out
		if runWithTimeout(cmd, 20*time.Second) != nil {
			continue
		}
		lines := strings.Fields(strings.TrimSpace(strings.ReplaceAll(out.String(), "\r", "")))
		if len(lines) < 2 || lines[len(lines)-1] != "1" {
			continue
		}
		py := strings.Join(lines[:len(lines)-1], " ")
		if pw := filepath.Join(filepath.Dir(py), "pythonw.exe"); fileExists(pw) {
			return pw
		}
		if fileExists(py) {
			return py
		}
	}
	return ""
}

// deleteSelfLater removes this temporary copy shortly after it exits.
func deleteSelfLater() {
	self := selfPath()
	cmd := exec.Command("cmd.exe")
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: createNoWindow,
		CmdLine: `cmd.exe /c ping 127.0.0.1 -n 3 >nul & del /f /q "` + self + `"`}
	if cmd.Start() == nil {
		cmd.Process.Release()
	}
}
