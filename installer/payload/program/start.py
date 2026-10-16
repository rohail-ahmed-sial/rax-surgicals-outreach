"""RAX Surgicals Outreach: start the dashboard.

Installed with RAX-Surgicals-Outreach-Setup.exe:  use the RAX Surgicals Outreach icon (this file is started for you)
From the zip on your PC:  python start.py              (opens the dashboard in its own window)
On a server:              python start.py --server     (asks for login; put HTTPS in front, see SERVER_SETUP.md)
Set the password:         python start.py --set-password
"""
import argparse, getpass, json, os, subprocess, sys, threading, urllib.request, webbrowser

if sys.version_info < (3, 9):
    sys.exit('Python 3.9 or newer is needed. Download it from https://www.python.org/downloads/')

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

# Windows has no time zone database of its own; a copy ships in the "tzdata" folder (office hours need it)
if os.name == 'nt' and os.path.isdir(os.path.join(ROOT, 'tzdata')):
    try:
        import zoneinfo
        zoneinfo.reset_tzpath([os.path.join(ROOT, 'tzdata')])
    except Exception:  # noqa
        pass

from app import db, server  # noqa: E402

WINDOWLESS = sys.stdout is None or sys.stderr is None      # started without a console (desktop icon)


def keep_messages_in_a_file():
    """Without a console, messages and errors go to data/rax.log so a problem can still be looked up."""
    os.makedirs(db.DATA_DIR, exist_ok=True)
    path = os.path.join(db.DATA_DIR, 'rax.log')
    try:
        if os.path.getsize(path) > 2_000_000:
            os.replace(path, path + '.old')
    except OSError:
        pass
    f = open(path, 'a', encoding='utf-8', buffering=1)
    sys.stdout = sys.stdout or f
    sys.stderr = sys.stderr or f


def tell(msg):
    """Print, and without a console also show a small Windows message box."""
    print(msg)
    if WINDOWLESS and os.name == 'nt':
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, msg, db.NAME, 0x40)
        except Exception:  # noqa
            pass


def already_running(port):
    """True if the app already answers on this port (started earlier, or with Windows). It answers with the name it
    had before 2.2, so copies of both versions recognise each other."""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # never through a proxy: this is this PC
        with opener.open(f'http://127.0.0.1:{port}/api/me', timeout=3) as r:
            return json.loads(r.read().decode('utf-8')).get('app') == 'RAX Outreach'
    except Exception:  # noqa
        return False


def app_browsers():
    """Browsers that can show a page as its own app window, without tabs or an address bar (Edge comes with Windows)."""
    if os.name != 'nt':
        return []
    bases = [os.environ.get(k) for k in ('ProgramFiles(x86)', 'ProgramFiles', 'LOCALAPPDATA')]
    found = []
    for rel in (('Microsoft', 'Edge', 'Application', 'msedge.exe'), ('Google', 'Chrome', 'Application', 'chrome.exe')):
        for base in bases:
            if base and os.path.isfile(os.path.join(base, *rel)):
                found.append(os.path.join(base, *rel))
    return found


def window_profile():
    """The browser profile of the app's window, used by nothing else. Extensions installed in the normal browser
    (translators, AI helpers, ad blockers) would otherwise add their buttons and boxes to the window.
    The installed app's launcher says where it is; the zip version keeps it in the user's AppData."""
    if os.environ.get('RAX_WINDOW_PROFILE'):
        return os.environ['RAX_WINDOW_PROFILE']
    base = os.environ.get('LOCALAPPDATA') or os.path.join(os.path.expanduser('~'), 'AppData', 'Local')
    return os.path.join(base, db.NAME, 'window')


def work_area():
    """The screen area outside the taskbar, in the units the browser uses for window sizes, or None."""
    if os.name != 'nt':
        return None
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        r = wintypes.RECT()
        if not user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0):     # SPI_GETWORKAREA
            return None
        scale = 1.0
        if user32.IsProcessDPIAware():                                        # real pixels: scale back to 1/96 inch
            try:
                scale = max(1.0, user32.GetDpiForSystem() / 96)
            except Exception:  # noqa: Windows before 10
                pass
        return tuple(int(v / scale) for v in (r.left, r.top, r.right - r.left, r.bottom - r.top))
    except Exception:  # noqa
        return None


def window_args(url, profile, size=(1360, 880)):
    """Browser options for the app's window: app mode on its own profile, no extensions, no translate bar,
    no first-run pages. The first time it opens centred; later the browser remembers the size and place."""
    args = [f'--app={url}', f'--user-data-dir={profile}', '--no-first-run', '--no-default-browser-check',
            '--disable-extensions', '--disable-sync', '--disable-features=Translate', '--hide-crash-restore-bubble']
    if not os.path.isdir(profile):
        w, h = size
        area = work_area()
        if area and area[2] > 200 and area[3] > 200:
            x0, y0, aw, ah = area
            w, h = min(w, aw - 32), min(h, ah - 32)
            args.append(f'--window-position={x0 + (aw - w) // 2},{y0 + (ah - h) // 2}')
        args.append(f'--window-size={w},{h}')
    return args


def open_window(url):
    """Show the dashboard in its own window; fall back to the normal browser."""
    profile = window_profile()
    for exe in app_browsers():
        try:
            subprocess.Popen([exe] + window_args(url, profile), close_fds=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            continue
    webbrowser.open(url)


def main():
    if WINDOWLESS:
        keep_messages_in_a_file()
    p = argparse.ArgumentParser(description=db.NAME)
    p.add_argument('--server', action='store_true', help='run on a server: listen on all addresses and require a password')
    p.add_argument('--host', default=None)
    p.add_argument('--port', type=int, default=int(os.environ.get('PORT', 8765)))
    p.add_argument('--set-password', action='store_true')
    p.add_argument('--no-browser', action='store_true', help='do not open the dashboard (used when starting with Windows)')
    p.add_argument('--window', action='store_true', help='open the dashboard in its own window (the default on Windows)')
    a = p.parse_args()
    url = f'http://127.0.0.1:{a.port}/'
    if not a.set_password and not a.server and already_running(a.port):
        print(f'{db.NAME} is already running: {url}')
        if not a.no_browser:
            open_window(url)
        return
    db.init()
    if a.set_password:
        pw = os.environ.get('RAX_NEW_PASSWORD') or getpass.getpass('New password (8+ characters): ')
        if len(pw) < 8:
            sys.exit('Too short.')
        if not os.environ.get('RAX_NEW_PASSWORD') and getpass.getpass('Again: ') != pw:
            sys.exit('The two passwords are different.')
        db.put('admin_password_hash', server.hash_pw(pw))
        print('Password saved.')
        return
    host = a.host or ('0.0.0.0' if a.server else '127.0.0.1')
    if a.server and not db.get('admin_password_hash'):
        sys.exit('Set a password first:  python start.py --set-password')
    try:
        httpd = server.serve(host, a.port, require_login=a.server)
    except OSError as e:
        tell(f'{db.NAME} could not start: port {a.port} is used by another program ({e}).\n\n'
             f'Close that program, or start with another port:  python start.py --port {a.port + 1}')
        sys.exit(1)
    print(f'{db.NAME} {db.VERSION} is running: {url}' + ('' if not a.server else f'  (listening on {host}:{a.port})'))
    if not WINDOWLESS:
        print('Keep this window open. Close it (or press Ctrl+C) to stop. Data is saved in the "data" folder.')
    if not a.server and not a.no_browser:
        threading.Timer(0.8, lambda: open_window(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    print('Stopped.')


if __name__ == '__main__':
    main()
