"""Builds dist/RAX_Surgicals_Outreach_v<version>.zip: the zip version (servers, Mac, Linux, or Windows with your own
Python), with the sources of the Windows setup and the tests. Top folder RAX_Surgicals_Outreach.

usage: python3 tools/package_zip.py"""
import os, re, sys, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION = re.search(r"VERSION = '([^']+)'", open(os.path.join(ROOT, 'app', 'db.py')).read()).group(1)
TOP = 'RAX_Surgicals_Outreach'
OUT = os.path.join(ROOT, 'dist', f'{TOP}_v{VERSION}.zip')
FILES = ['README.md', 'SERVER_SETUP.md', 'Start RAX Surgicals Outreach (Windows).bat', 'sample_leads.csv', 'start.py', 'start_mac_linux.sh']
DIRS = ['app', 'installer', 'logo', 'tests', 'tools', 'tzdata']
SKIP_DIRS = {'__pycache__', 'payload', 'shots', 'data'}


def entries():
    for f in FILES:
        yield f
    for d in DIRS:
        for root, dirs, files in os.walk(os.path.join(ROOT, d)):
            dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
            for f in sorted(files):
                if not f.endswith('.pyc'):
                    yield os.path.relpath(os.path.join(root, f), ROOT)


os.makedirs(os.path.dirname(OUT), exist_ok=True)
names = list(entries())
with zipfile.ZipFile(OUT, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for n in names:
        info = zipfile.ZipInfo.from_file(os.path.join(ROOT, n), TOP + '/' + n.replace(os.sep, '/'))
        if n.endswith('.sh'):
            info.external_attr = (0o755 << 16)
        with open(os.path.join(ROOT, n), 'rb') as fh:
            z.writestr(info, fh.read(), zipfile.ZIP_DEFLATED)
with zipfile.ZipFile(OUT) as z:
    assert z.testzip() is None
    assert not [n for n in z.namelist() if '__pycache__' in n or '/payload/' in n or n.endswith('.pyc')]
print(f'{os.path.relpath(OUT, ROOT)}: {len(names)} files, {os.path.getsize(OUT) // 1024} KB')
