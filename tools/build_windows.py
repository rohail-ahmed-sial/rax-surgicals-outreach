"""Builds RAX-Surgicals-Outreach-Setup.exe: the Windows setup and launcher (Go, no other tools needed).

usage: python3 tools/build_windows.py [--linux-test]
  dist/RAX-Surgicals-Outreach-Setup.exe     the file to give to users
  build/rax-setup-linux          the same program built for Linux, used by tests/setup_test.py
"""
import os, shutil, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INST = os.path.join(ROOT, 'installer')
GO = shutil.which('go') or '/usr/local/go1.25.1/bin/go'
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import winres  # noqa: E402

SKIP = {'__pycache__', 'data', 'shots'}


def copytree(src, dst):
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in SKIP]
        rel = os.path.relpath(root, src)
        os.makedirs(os.path.join(dst, rel), exist_ok=True)
        for f in files:
            if f.endswith('.pyc'):
                continue
            shutil.copy2(os.path.join(root, f), os.path.join(dst, rel, f))


def payload():
    p = os.path.join(INST, 'payload')
    shutil.rmtree(p, ignore_errors=True)
    prog = os.path.join(p, 'program')
    os.makedirs(prog)
    shutil.copy2(os.path.join(ROOT, 'start.py'), prog)
    copytree(os.path.join(ROOT, 'app'), os.path.join(prog, 'app'))
    copytree(os.path.join(ROOT, 'tzdata'), os.path.join(prog, 'tzdata'))
    copytree(os.path.join(ROOT, 'logo'), os.path.join(p, 'logo'))
    shutil.copy2(os.path.join(ROOT, 'app', 'static', 'img', 'rax.ico'), os.path.join(p, 'rax.ico'))
    for f in ('atkinson-hyperlegible-next.woff2', 'charis-sil-bold.woff2'):
        shutil.copy2(os.path.join(ROOT, 'app', 'static', 'fonts', f), os.path.join(INST, 'assets', f))
    shutil.copy2(os.path.join(ROOT, 'app', 'static', 'img', 'icon.svg'), os.path.join(INST, 'assets', 'icon.svg'))
    n = sum(len(fs) for _, _, fs in os.walk(p))
    print(f'payload: {n} files')


def go_build(goos, out, extra_ld=''):
    env = dict(os.environ, GOOS=goos, GOARCH='amd64', CGO_ENABLED='0', GOFLAGS='-mod=mod', GOPROXY='off',
               GOCACHE=os.environ.get('GOCACHE', '/tmp/claude-0/gocache'), PATH=os.path.dirname(GO) + ':' + os.environ['PATH'])
    os.makedirs(os.path.dirname(out), exist_ok=True)
    subprocess.run([GO, 'vet', './...'], cwd=INST, env=env, check=True)
    subprocess.run([GO, 'build', '-trimpath', '-ldflags', '-s -w -buildid= ' + extra_ld, '-o', out, '.'], cwd=INST, env=env, check=True)
    print(f'built {os.path.relpath(out, ROOT)} ({os.path.getsize(out) // 1024} KB)')


if __name__ == '__main__':
    payload()
    winres.make(os.path.join(ROOT, 'app', 'static', 'img', 'rax.ico'), os.path.join(INST, 'rsrc_windows_amd64.syso'))
    exe = os.path.join(ROOT, 'dist', 'RAX-Surgicals-Outreach-Setup.exe')
    go_build('windows', exe, '-H=windowsgui')
    winres.check(exe)
    if '--linux-test' in sys.argv:
        go_build('linux', os.path.join(ROOT, 'build', 'rax-setup-linux'))
