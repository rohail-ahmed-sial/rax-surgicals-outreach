"""Tests the Windows setup program's flow using its Linux build (Windows parts replaced by stand-ins under a temp folder):
install through the setup window, open the app, update over a running copy, start in the background,
the fallback when Python cannot be downloaded, uninstall with and without deleting the data, and the update from
RAX Outreach 2.1 (the name before 2.2), which moves its data and Python to the new folders.

    python3 tools/build_windows.py --linux-test && python3 tests/setup_test.py

The update from 2.1 needs the Linux build of version 2.1 as build/rax-setup-linux-2.1 (build it from the 2.1 sources
with the same command); without it that part is skipped.
"""
import http.server, io, json, os, shutil, socket, socketserver, subprocess, sys, tempfile, threading, time, urllib.request, zipfile
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETUP = os.path.join(ROOT, 'build', 'rax-setup-linux')
OLD_SETUP = os.path.join(ROOT, 'build', 'rax-setup-linux-2.1')
NAME, OLD = 'RAX Surgicals Outreach', 'RAX Outreach'
SLOGAN = 'Find buyers. Email them. Turn replies into orders.'
UNINST = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\RAX Outreach'     # the key keeps the old name
RUN = r'Software\Microsoft\Windows\CurrentVersion\Run'
OK = FAIL = 0


def check(cond, label, info=''):
    global OK, FAIL
    if cond:
        OK += 1
        print('  pass', label)
    else:
        FAIL += 1
        print('  FAIL', label, info)


# a stand-in for python.org's embeddable Python: "pythonw" runs this machine's python3
def runtime_package(prefix='', padding=0):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        info = zipfile.ZipInfo(prefix + 'pythonw')
        info.external_attr = (0o755 << 16)
        z.writestr(info, '#!/bin/sh\nexec python3 "$@"\n')
        z.writestr(prefix + 'python3-test.dll', 'stand-in')
        z.writestr(prefix + 'python313._pth', 'python313.zip\n.\n')
        if padding:   # incompressible filler, so a download takes several pieces
            z.writestr(zipfile.ZipInfo(prefix + 'Lib/filler.bin'), os.urandom(padding))
        if prefix:
            z.writestr('python.nuspec', '<package/>')
    return buf.getvalue()


RUNTIME_ZIP = runtime_package()
BIG_ZIP = runtime_package(padding=600_000)
NUPKG = runtime_package('tools/')
REQUESTS = []


class Files(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        REQUESTS.append((self.path, self.headers.get('Range')))
        body = {'/python.zip': RUNTIME_ZIP, '/stall.zip': BIG_ZIP, '/python.3.13.3.nupkg': NUPKG}.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        start = 0
        rng = self.headers.get('Range')
        if rng and self.path == '/stall.zip':
            start = int(rng.split('=')[1].rstrip('-'))
            self.send_response(206)
            self.send_header('Content-Range', f'bytes {start}-{len(body) - 1}/{len(body)}')
        else:
            self.send_response(200)
        self.send_header('Content-Length', str(len(body) - start))
        self.end_headers()
        first = self.path == '/stall.zip' and sum(1 for r in REQUESTS if r[0] == '/stall.zip') == 1
        for i in range(start, len(body), 4096):
            if first and i >= 250_000:   # the line goes quiet in the middle of the first try
                time.sleep(4)
                return
            self.wfile.write(body[i:i + 4096])

    def log_message(self, *a):
        pass


files = socketserver.ThreadingTCPServer(('127.0.0.1', 0), Files)
threading.Thread(target=files.serve_forever, daemon=True).start()
FILES = f'http://127.0.0.1:{files.server_address[1]}'

HOME = tempfile.mkdtemp(prefix='rax-setup-test-')
INSTALL = os.path.join(HOME, 'LocalAppData', 'Programs', NAME)
DATA = os.path.join(HOME, 'LocalAppData', NAME, 'data')
LAUNCHER = os.path.join(INSTALL, NAME)
OLD_INSTALL = os.path.join(HOME, 'LocalAppData', 'Programs', OLD)
OLD_ROOT = os.path.join(HOME, 'LocalAppData', OLD)
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def env(**extra):
    e = dict(os.environ, RAX_TEST_HOME=HOME, RAX_TEST_RUNTIME_URL=FILES + '/python.zip', BROWSER='true', RAX_NO_WORKER='1')
    e.update({k: v for k, v in extra.items() if v is not None})
    return e


def registry():
    try:
        return json.load(open(os.path.join(HOME, 'registry.json')))
    except OSError:
        return {}


def app_up():
    try:   # both versions answer with the old name: that is how setup recognises a running copy
        return json.loads(op.open('http://127.0.0.1:8765/api/me', timeout=2).read()).get('app') == 'RAX Outreach'
    except Exception:  # noqa
        return False


def wait(fn, secs=20):
    end = time.time() + secs
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.25)
    return False


def opened_urls():
    try:
        return open(os.path.join(HOME, 'opened.txt')).read().split('\n')
    except OSError:
        return []


INITIAL = {}


def run_setup(pw, desktop=True, autostart=True, expect='done', setup=SETUP, **extra):
    """Starts the setup program, drives its window, returns (process, page, title). INITIAL keeps what the window
    showed before anything was clicked."""
    before = len([u for u in opened_urls() if u])
    proc = subprocess.Popen([setup], env=env(**extra), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    wait(lambda: len([u for u in opened_urls() if u]) > before, 10)
    url = [u for u in opened_urls() if u][-1].split(' ')[0].removeprefix('--app=')
    pg = pw.new_page()
    pg.goto(url)
    pg.wait_for_selector('#b-go')
    pg.wait_for_timeout(300)
    INITIAL.update(desktop=pg.is_checked('#o-desktop'), autostart=pg.is_checked('#o-auto'), lead=pg.inner_text('#lead'),
                   where=pg.inner_text('#where'), header=pg.inner_text('header'), version=pg.inner_text('#ver'))
    if pg.is_checked('#o-desktop') != desktop:
        pg.click('#o-desktop')
    if pg.is_checked('#o-auto') != autostart:
        pg.click('#o-auto')
    title = pg.inner_text('#title')
    pg.click('#b-go')
    pg.wait_for_function(f"() => document.querySelector('#b-go').textContent.includes({json.dumps('Open' if expect == 'done' else 'Try again')})", timeout=30000)
    return proc, pg, title


with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context()

    print('1. First install')
    proc, pg, title = run_setup(ctx)
    check(title == 'Install RAX Surgicals Outreach', 'setup window says Install', title)
    check(NAME in INITIAL['header'] and SLOGAN in INITIAL['header'] and INITIAL['version'] == 'Version 2.2', 'the name and slogan at the top, the version below', INITIAL)
    line = [u for u in opened_urls() if u][-1]
    check('--user-data-dir=' + os.path.join(tempfile.gettempdir(), 'RAX Surgicals Outreach Setup window') in line and '--disable-extensions' in line
          and '--no-first-run' in line and '--disable-features=Translate' in line and '--window-size=780,660' in line
          and '--window-position=293,34' in line, 'setup window: own clean browser profile, no extensions, centred', line)
    steps = pg.eval_on_selector_all('#steps li', 'els => els.map(e => e.className)')
    check(steps and all(s in ('done', 'skip') for s in steps), 'every step finished', steps)
    check(os.path.isfile(os.path.join(INSTALL, 'program', 'start.py')) and os.path.isdir(os.path.join(INSTALL, 'program', 'app', 'static'))
          and os.path.isfile(os.path.join(INSTALL, 'program', 'tzdata', 'Asia', 'Karachi')), 'program files, dashboard and time zones copied')
    check(os.access(os.path.join(INSTALL, 'runtime', 'pythonw'), os.X_OK), 'Python runtime downloaded and unpacked')
    check(os.path.isfile(LAUNCHER) and os.path.isfile(os.path.join(INSTALL, 'rax.ico')) and os.path.isdir(os.path.join(INSTALL, 'logo')), 'launcher, icon and logo files in place')
    reg = registry()
    un = reg.get(UNINST, {})
    check(un.get('DisplayName') == NAME and un.get('DisplayVersion') == '2.2' and un.get('Publisher') == 'RAX Surgicals' and un.get('Comments') == SLOGAN
          and un.get('UninstallString') == f'"{LAUNCHER}" --uninstall' and un.get('EstimatedSize', 0) > 1000, 'listed in Apps with its name, publisher, version and uninstall command', un)
    check(reg.get(RUN, {}).get(NAME) == f'"{LAUNCHER}" --background', 'starts with Windows (chosen)')
    menu, desk = os.path.join(HOME, 'Programs', NAME + '.lnk'), os.path.join(HOME, 'Desktop', NAME + '.lnk')
    check(os.path.isfile(menu) and os.path.isfile(desk) and SLOGAN in open(menu).read(), 'Start menu and desktop icons, with the slogan as their description')

    print('2. Open the app from the finished setup')
    pg.click('#b-go')
    check(wait(app_up, 25), 'the app starts and answers')
    me = json.loads(op.open('http://127.0.0.1:8765/api/me').read())
    check(me.get('installed') is True and me.get('version') == '2.2' and me.get('name') == NAME, 'the app knows it is the installed copy', me)
    check(os.path.isfile(os.path.join(DATA, 'outreach.db')) and os.path.isfile(os.path.join(DATA, 'stop.token')), 'data kept outside the program folder')
    check(wait(lambda: proc.poll() is not None, 10), 'setup closes itself after opening the app')
    auto = json.loads(op.open('http://127.0.0.1:8765/api/autostart').read())
    check(auto == {'supported': False, 'on': False}, 'start-with-Windows switch is hidden off Windows', auto)

    print('3. Opening it again while it runs')
    subprocess.run([LAUNCHER], env=env(), timeout=20)
    time.sleep(2)
    check(app_up(), 'still one copy running')

    print('4. Update over the running copy')
    proc, pg, title = run_setup(ctx)
    check(title == 'Update RAX Surgicals Outreach', 'setup window says Update', title)
    details = pg.eval_on_selector_all('#steps li', 'els => els.map(e => e.className + ": " + e.innerText.replace(/\\n/g, " "))')
    check(any('Closing' in d and d.startswith('done') for d in details), 'the running copy was asked to stop', details)
    check(any('Python' in d and 'Already there' in d for d in details), 'Python not downloaded again', details)
    check(not app_up(), 'old copy stopped during the update')
    closed = open(os.path.join(HOME, 'closed.txt')).read() if os.path.exists(os.path.join(HOME, 'closed.txt')) else ''
    check(os.path.join(HOME, 'LocalAppData', NAME, 'window') in closed, 'the open app window is closed for the update', closed)
    pg.click('#b-cancel')
    check(wait(lambda: proc.poll() is not None, 10), 'Close ends the setup')

    print('5. Start in the background (as Windows does at sign-in)')
    subprocess.run([LAUNCHER, '--background'], env=env(), timeout=20)
    check(wait(app_up, 25), 'app runs without opening a window')

    req = urllib.request.Request('http://127.0.0.1:8765/api/settings', data=json.dumps({'company_name': 'Kept Co'}).encode(), method='POST',
                                 headers={'Content-Type': 'application/json', 'X-Requested-With': 'rax'})
    op.open(req).read()

    print('6. Uninstall, keeping the data')
    profile = os.path.join(HOME, 'LocalAppData', NAME, 'window')
    os.makedirs(os.path.join(profile, 'Default'), exist_ok=True)
    open(os.path.join(profile, 'Default', 'Preferences'), 'w').write('{}')
    subprocess.run([LAUNCHER, '--uninstall'], env=env(RAX_TEST_ANSWERS='yes,no'), timeout=30)
    check(wait(lambda: not os.path.exists(INSTALL), 20), 'program folder removed')
    check(not app_up(), 'the app was stopped first')
    check(os.path.isfile(os.path.join(DATA, 'outreach.db')), 'data kept')
    check(wait(lambda: not os.path.exists(profile), 10), 'the window\'s browser profile removed (it is not data)')
    reg = registry()
    check(UNINST not in reg and NAME not in reg.get(RUN, {}), 'Apps entry and start-with-Windows removed')
    check(not os.path.exists(os.path.join(HOME, 'Desktop', NAME + '.lnk')) and not os.path.exists(os.path.join(HOME, 'Programs', NAME + '.lnk')), 'icons removed')
    msgs = open(os.path.join(HOME, 'messages.txt')).read()
    check(NAME + ' was removed' in msgs, 'tells that it is done')

    print('7. Python cannot be downloaded: a Python already on the PC is used')
    proc, pg, title = run_setup(ctx, desktop=False, autostart=False, RAX_TEST_RUNTIME_URL=FILES + '/missing.zip')
    details = pg.eval_on_selector_all('#steps li', 'els => els.map(e => e.innerText.replace(/\\n/g, " "))')
    check(any('already on this PC' in d for d in details), 'falls back to the installed Python', details)
    check(not os.path.exists(os.path.join(HOME, 'Desktop', NAME + '.lnk')), 'no desktop icon when not wanted')
    check(NAME not in registry().get(RUN, {}), 'no start-with-Windows when not wanted')
    pg.click('#b-go')
    check(wait(app_up, 25), 'app starts on that Python')
    check(json.loads(op.open('http://127.0.0.1:8765/api/settings').read()).get('company_name') == 'Kept Co', 'the kept data opens again')

    print('8. Uninstall and delete the data')
    subprocess.run([LAUNCHER, '--uninstall'], env=env(RAX_TEST_ANSWERS='yes,yes'), timeout=30)
    check(wait(lambda: not os.path.exists(INSTALL), 20) and wait(lambda: not os.path.exists(os.path.dirname(DATA)), 10), 'program and data removed')

    print('9. No internet and no Python: a clear message and Try again')
    proc, pg, title = run_setup(ctx, expect='error', RAX_TEST_RUNTIME_URL=FILES + '/missing.zip', RAX_TEST_NO_SYSTEM_PYTHON='1')
    err = pg.inner_text('#steps')
    check('Check the internet connection' in err, 'explains what to do', err)
    pg.click('#b-cancel')
    wait(lambda: proc.poll() is not None, 10)

    print('10. Declining the uninstall changes nothing')
    proc, pg, title = run_setup(ctx)
    pg.click('#b-cancel')
    wait(lambda: proc.poll() is not None, 10)
    subprocess.run([LAUNCHER, '--uninstall'], env=env(RAX_TEST_ANSWERS='no'), timeout=30)
    time.sleep(1)
    check(os.path.isfile(LAUNCHER), 'still installed after No')
    subprocess.run([LAUNCHER, '--uninstall'], env=env(RAX_TEST_ANSWERS='yes,yes'), timeout=30)
    wait(lambda: not os.path.exists(INSTALL), 20)

    print('11. The download stops in the middle: it continues where it stopped')
    REQUESTS.clear()
    proc, pg, title = run_setup(ctx, RAX_TEST_RUNTIME_URL=FILES + '/stall.zip', RAX_TEST_STALL_MS='800', RAX_TEST_NO_SYSTEM_PYTHON='1')
    tries = [r for r in REQUESTS if r[0] == '/stall.zip']
    check(len(tries) == 2 and tries[1][1] and tries[1][1].startswith('bytes=') and int(tries[1][1][6:].rstrip('-')) >= 200_000,
          'second connection asks only for the rest of the file', tries)
    check(os.path.isfile(os.path.join(INSTALL, 'runtime', 'Lib', 'filler.bin')) and os.path.getsize(os.path.join(INSTALL, 'runtime', 'Lib', 'filler.bin')) == 600_000,
          'the joined download is complete and unpacked')
    pg.click('#b-cancel'); wait(lambda: proc.poll() is not None, 10)
    subprocess.run([LAUNCHER, '--uninstall'], env=env(RAX_TEST_ANSWERS='yes,yes'), timeout=30)
    wait(lambda: not os.path.exists(INSTALL), 20)

    print('12. python.org does not have it: the NuGet package is used')
    proc, pg, title = run_setup(ctx, RAX_TEST_RUNTIME_URL=FILES + '/missing.zip ' + FILES + '/python.3.13.3.nupkg', RAX_TEST_NO_SYSTEM_PYTHON='1')
    details = pg.eval_on_selector_all('#steps li', 'els => els.map(e => e.innerText.replace(/\\n/g, " "))')
    check(os.access(os.path.join(INSTALL, 'runtime', 'pythonw'), os.X_OK) and not os.path.exists(os.path.join(INSTALL, 'runtime', 'python.nuspec'))
          and any('Downloaded from' in d for d in details), 'Python taken from the package\'s tools folder', details)
    pg.click('#b-go')
    check(wait(app_up, 25), 'the app starts on it')
    subprocess.run([LAUNCHER, '--uninstall'], env=env(RAX_TEST_ANSWERS='yes,yes'), timeout=30)
    wait(lambda: not os.path.exists(INSTALL), 20)

    print('13. A Python file next to the setup is used, without internet')
    dl = os.path.join(HOME, 'dl'); os.makedirs(dl, exist_ok=True)
    shutil.copy2(SETUP, os.path.join(dl, 'RAX-Surgicals-Outreach-Setup'))
    open(os.path.join(dl, 'python-3.13.3-embed-amd64.zip'), 'wb').write(RUNTIME_ZIP)
    REQUESTS.clear()
    proc, pg, title = run_setup(ctx, setup=os.path.join(dl, 'RAX-Surgicals-Outreach-Setup'), RAX_TEST_RUNTIME_URL=FILES + '/missing.zip', RAX_TEST_NO_SYSTEM_PYTHON='1')
    details = pg.eval_on_selector_all('#steps li', 'els => els.map(e => e.innerText.replace(/\\n/g, " "))')
    check(any('python-3.13.3-embed-amd64.zip' in d for d in details) and not REQUESTS, 'used the file on this PC, nothing downloaded', (details, REQUESTS))
    pg.click('#b-cancel'); wait(lambda: proc.poll() is not None, 10)
    subprocess.run([LAUNCHER, '--uninstall'], env=env(RAX_TEST_ANSWERS='yes,yes'), timeout=30)
    wait(lambda: not os.path.exists(INSTALL), 20)

    print('14. Update from RAX Outreach 2.1: data and Python move to the new folders, the old name goes')
    if not os.path.isfile(OLD_SETUP):
        print('  skipped: build/rax-setup-linux-2.1 is missing')
    else:
        proc, pg, title = run_setup(ctx, setup=OLD_SETUP)
        check(title == 'Install RAX Outreach' and os.path.isfile(os.path.join(OLD_INSTALL, OLD)), 'version 2.1 installed under its old name', title)
        pg.click('#b-go')
        check(wait(app_up, 25), 'version 2.1 runs')
        req = urllib.request.Request('http://127.0.0.1:8765/api/settings', data=json.dumps({'company_name': 'Moved Co'}).encode(), method='POST',
                                     headers={'Content-Type': 'application/json', 'X-Requested-With': 'rax'})
        op.open(req).read()
        os.makedirs(os.path.join(OLD_ROOT, 'window', 'Default'), exist_ok=True)
        open(os.path.join(OLD_ROOT, 'window', 'Default', 'Preferences'), 'w').write('{"size": "remembered"}')
        open(os.path.join(OLD_ROOT, 'data', 'files', 'catalogue.pdf'), 'wb').write(b'%PDF stand-in')
        os.makedirs(os.path.join(OLD_ROOT, 'data', 'backups'), exist_ok=True)
        open(os.path.join(OLD_ROOT, 'data', 'backups', '2026-10-14.db'), 'wb').write(b'SQLite format 3\x00 stand-in')
        reg = registry()
        check(reg.get(UNINST, {}).get('DisplayName') == OLD and OLD in reg.get(RUN, {}) and os.path.isfile(os.path.join(HOME, 'Desktop', OLD + '.lnk')),
              'its Apps entry, start-with-Windows and icons are there', reg)
        REQUESTS.clear()
        proc, pg, title = run_setup(ctx, RAX_TEST_RUNTIME_URL=FILES + '/missing.zip', RAX_TEST_NO_SYSTEM_PYTHON='1')
        check(title == 'Update RAX Surgicals Outreach' and 'now called RAX Surgicals Outreach' in INITIAL['lead'], 'the new setup offers an update and says the name changed', (title, INITIAL))
        check(INITIAL['autostart'] and 'about 11 MB' not in INITIAL['where'], 'it keeps start-with-Windows on, and knows Python is already there', INITIAL)
        details = pg.eval_on_selector_all('#steps li', 'els => els.map(e => e.className + ": " + e.innerText.replace(/\\n/g, " "))')
        check(any(d.startswith('done') and 'Closing RAX Outreach' in d for d in details), 'the running 2.1 was stopped', details)
        check(any(d.startswith('done') and 'Moving your data from RAX Outreach' in d and DATA in d for d in details), 'the data moved', details)
        check(any(d.startswith('done') and 'Kept from RAX Outreach' in d for d in details) and not REQUESTS, 'Python taken over, nothing downloaded', (details, REQUESTS))
        check(not os.path.exists(OLD_INSTALL) and not os.path.exists(OLD_ROOT), 'the old program and data folders are gone')
        check(os.path.isfile(os.path.join(DATA, 'outreach.db')) and os.path.isfile(os.path.join(DATA, 'files', 'catalogue.pdf'))
              and os.path.isfile(os.path.join(DATA, 'backups', '2026-10-14.db')), 'database, files and backups in the new folder',
              [os.path.relpath(os.path.join(r, f), DATA) for r, _, fs in os.walk(DATA) for f in fs])
        check(os.path.isfile(os.path.join(HOME, 'LocalAppData', NAME, 'window', 'Default', 'Preferences')), 'the window keeps its remembered size and place')
        reg = registry()
        check(OLD not in reg.get(RUN, {}) and reg.get(RUN, {}).get(NAME) == f'"{LAUNCHER}" --background', 'start-with-Windows now starts the new program', reg.get(RUN))
        check(not any(os.path.exists(os.path.join(HOME, d, OLD + '.lnk')) for d in ('Programs', 'Desktop', 'Startup'))
              and os.path.isfile(os.path.join(HOME, 'Programs', NAME + '.lnk')) and os.path.isfile(os.path.join(HOME, 'Desktop', NAME + '.lnk')), 'old icons replaced by new ones')
        un = reg.get(UNINST, {})
        check(un.get('DisplayName') == NAME and un.get('DisplayVersion') == '2.2' and un.get('InstallLocation') == INSTALL, 'Settings > Apps shows the new name and version', un)
        pg.click('#b-go')
        check(wait(app_up, 25), 'the new version starts')
        check(json.loads(op.open('http://127.0.0.1:8765/api/settings').read()).get('company_name') == 'Moved Co'
              and json.loads(op.open('http://127.0.0.1:8765/api/me').read()).get('version') == '2.2', 'with the data of 2.1')
        subprocess.run([LAUNCHER, '--uninstall'], env=env(RAX_TEST_ANSWERS='yes,yes'), timeout=30)
        check(wait(lambda: not os.path.exists(INSTALL), 20) and wait(lambda: not os.path.exists(os.path.dirname(DATA)), 10)
              and not os.path.exists(OLD_INSTALL) and not os.path.exists(OLD_ROOT), 'uninstall removes everything, old and new')
    browser.close()

shutil.rmtree(HOME, ignore_errors=True)
print(f'\n{OK} passed, {FAIL} failed')
sys.exit(1 if FAIL else 0)
