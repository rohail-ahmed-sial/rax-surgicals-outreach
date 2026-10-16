"""Checks the dashboard texts: every text code used in the scripts (such as err.offline or lint.too_long) must have an
English entry in i18n.js. Plain English labels are their own text and need no entry.
usage: python3 tools/i18n_keys.py"""
import re, os, sys, json, subprocess
ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app', 'static', 'js')
files = [os.path.join(dp, f) for dp, _, fs in os.walk(ROOT) for f in fs if f.endswith('.js') and f != 'i18n.js']
src = '\n'.join(open(f, encoding='utf-8').read() for f in files)
keys = set()
# t('x'), T('x'), R.t('x'), R.T('x'): first argument string literal (single quotes, handles \' inside)
for m in re.finditer(r"""(?<![\w.])(?:R\.)?[tT]\(\s*'((?:[^'\\]|\\.)*)'""", src):
    keys.add(m.group(1).replace("\\'", "'"))
for m in re.finditer(r"""(?<![\w.])(?:R\.)?[tT]\(\s*"((?:[^"\\]|\\.)*)\"""", src):
    keys.add(m.group(1))
# keys built with a ternary inside t(): t(x ? 'a' : 'b')
for m in re.finditer(r"""(?<![\w.])(?:R\.)?[tT]\(([^()]*?\?[^()]*?)\)""", src):
    for s in re.findall(r"'((?:[^'\\]|\\.)*)'", m.group(1)):
        if s.strip(): keys.add(s.replace("\\'", "'"))
# what i18n.js defines (evaluate it with node)
node = subprocess.run(['node', '-e', '''
global.window = {}; require(process.argv[1]);
console.log(JSON.stringify(Object.keys(window.R.I18N.en)));
''', os.path.join(ROOT, 'i18n.js')], capture_output=True, text=True)
if node.returncode:
    sys.exit(node.stderr[:2000])
have = set(json.loads(node.stdout))
missing = sorted(k for k in keys if re.fullmatch(r'[a-z_]+(\.[a-z0-9_]+)+', k) and k not in have)
print(f'{len(keys)} texts used; text codes without an English entry: {len(missing)}')
for k in missing:
    print('  ', k)
sys.exit(1 if missing else 0)
