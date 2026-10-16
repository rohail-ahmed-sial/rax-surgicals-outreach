"""Windows resources for the Go build: the app icon, version details and a manifest, written as a COFF object
(rsrc_windows_amd64.syso) that the Go linker puts into the .exe. Also reads them back from a finished .exe to check.

usage: python3 tools/winres.py make  ICON.ico OUT.syso
       python3 tools/winres.py check FILE.exe
"""
import struct, sys

RT_ICON, RT_GROUP_ICON, RT_VERSION, RT_MANIFEST = 3, 14, 16, 24
LANG = 0x0409

def _app_version():
    """The version in installer/main.go (appVersion), so the file details always match the program."""
    import os, re
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'installer', 'main.go')).read()
    parts = [int(x) for x in re.search(r'appVersion\s*=\s*"([0-9.]+)"', src).group(1).split('.')]
    return tuple((parts + [0, 0, 0, 0])[:4])


VERSION = _app_version()
VERSION_TEXT = '.'.join(map(str, VERSION))
STRINGS = {
    'Comments': 'Find buyers. Email them. Turn replies into orders.',
    'CompanyName': 'RAX Surgicals',
    'FileDescription': 'RAX Surgicals Outreach',
    'FileVersion': VERSION_TEXT,
    'InternalName': 'RAX Surgicals Outreach',
    'LegalCopyright': '© 2026 RAX Surgicals',
    'OriginalFilename': 'RAX Surgicals Outreach.exe',
    'ProductName': 'RAX Surgicals Outreach',
    'ProductVersion': f'{VERSION[0]}.{VERSION[1]}',
}

MANIFEST = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <assemblyIdentity type="win32" name="RAXSurgicals.RAXSurgicalsOutreach" version="@VERSION@" processorArchitecture="amd64"/>
  <description>RAX Surgicals Outreach</description>
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3">
    <security>
      <requestedPrivileges>
        <requestedExecutionLevel level="asInvoker" uiAccess="false"/>
      </requestedPrivileges>
    </security>
  </trustInfo>
  <compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1">
    <application>
      <supportedOS Id="{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}"/>
    </application>
  </compatibility>
  <application xmlns="urn:schemas-microsoft-com:asm.v3">
    <windowsSettings>
      <dpiAware xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">true</dpiAware>
    </windowsSettings>
  </application>
  <dependency>
    <dependentAssembly>
      <assemblyIdentity type="win32" name="Microsoft.Windows.Common-Controls" version="6.0.0.0" processorArchitecture="*" publicKeyToken="6595b64144ccf1df" language="*"/>
    </dependentAssembly>
  </dependency>
</assembly>
'''
MANIFEST = MANIFEST.replace(b'@VERSION@', VERSION_TEXT.encode())


def utf16z(s):
    return s.encode('utf-16-le') + b'\x00\x00'


def pad4(b):
    while len(b) % 4:
        b += b'\x00'


def vblock(key, value=b'', wtype=1, children=(), vlen=None):
    """One VS_VERSIONINFO-style block: wLength, wValueLength, wType, key, padding, value, padded children."""
    b = bytearray(struct.pack('<HHH', 0, 0, wtype)) + utf16z(key)
    pad4(b)
    b += value
    for c in children:
        pad4(b)
        b += c
    struct.pack_into('<HH', b, 0, len(b), len(value) if vlen is None else vlen)
    return bytes(b)


def version_resource():
    ms, ls = (VERSION[0] << 16) | VERSION[1], (VERSION[2] << 16) | VERSION[3]
    ffi = struct.pack('<13I', 0xFEEF04BD, 0x00010000, ms, ls, ms, ls, 0x3F, 0, 0x40004, 1, 0, 0, 0)
    strs = [vblock(k, utf16z(v), 1, vlen=len(v) + 1) for k, v in STRINGS.items()]
    table = vblock('040904B0', b'', 1, strs, vlen=0)
    sfi = vblock('StringFileInfo', b'', 1, [table], vlen=0)
    var = vblock('Translation', struct.pack('<HH', 0x0409, 0x04B0), 0, vlen=4)
    vfi = vblock('VarFileInfo', b'', 1, [var], vlen=0)
    return vblock('VS_VERSION_INFO', ffi, 0, [sfi, vfi], vlen=52)


def read_ico(path):
    data = open(path, 'rb').read()
    _, typ, count = struct.unpack_from('<HHH', data, 0)
    assert typ == 1, 'not an icon file'
    out = []
    for i in range(count):
        w, h, colors, res, planes, bpp, size, offset = struct.unpack_from('<BBBBHHII', data, 6 + 16 * i)
        out.append((w, h, colors, bpp or 32, data[offset:offset + size]))
    return out


def build_rsrc(resources):
    """resources: {type: {id: bytes}} -> (section bytes, offsets of the RVA fields that need relocations)."""
    types = sorted(resources)
    off = 16 + 8 * len(types)
    tdir, ldir, dent, doff = {}, {}, {}, {}
    for t in types:
        tdir[t] = off
        off += 16 + 8 * len(resources[t])
    keys = [(t, i) for t in types for i in sorted(resources[t])]
    for k in keys:
        ldir[k] = off
        off += 16 + 8
    for k in keys:
        dent[k] = off
        off += 16
    for k in keys:
        off = (off + 7) & ~7
        doff[k] = off
        off += len(resources[k[0]][k[1]])
    buf = bytearray((off + 7) & ~7)

    def dirhdr(at, n):
        struct.pack_into('<IIHHHH', buf, at, 0, 0, 0, 0, 0, n)

    dirhdr(0, len(types))
    for a, t in enumerate(types):
        struct.pack_into('<II', buf, 16 + 8 * a, t, 0x80000000 | tdir[t])
        ids = sorted(resources[t])
        dirhdr(tdir[t], len(ids))
        for b, i in enumerate(ids):
            k = (t, i)
            struct.pack_into('<II', buf, tdir[t] + 16 + 8 * b, i, 0x80000000 | ldir[k])
            dirhdr(ldir[k], 1)
            struct.pack_into('<II', buf, ldir[k] + 16, LANG, dent[k])
            data = resources[t][i]
            struct.pack_into('<IIII', buf, dent[k], doff[k], len(data), 0, 0)
            buf[doff[k]:doff[k] + len(data)] = data
    return bytes(buf), [dent[k] for k in keys]


def coff(section, relocs):
    raw = 20 + 40
    rel_at = raw + len(section)
    sym_at = rel_at + 10 * len(relocs)
    fh = struct.pack('<HHIIIHH', 0x8664, 1, 0, sym_at, 1, 0, 0)
    sh = struct.pack('<8sIIIIIIHHI', b'.rsrc', 0, 0, len(section), raw, rel_at, 0, len(relocs), 0, 0x40000040)
    rel = b''.join(struct.pack('<IIH', r, 0, 3) for r in relocs)          # IMAGE_REL_AMD64_ADDR32NB to symbol 0
    sym = struct.pack('<8sIhHBB', b'.rsrc', 0, 1, 0, 3, 0)                  # the section, static
    return fh + sh + section + rel + sym + struct.pack('<I', 4)             # empty string table


def make(ico, out):
    icons = read_ico(ico)
    res = {RT_ICON: {}, RT_GROUP_ICON: {}, RT_VERSION: {1: version_resource()}, RT_MANIFEST: {1: MANIFEST}}
    grp = bytearray(struct.pack('<HHH', 0, 1, len(icons)))
    for n, (w, h, colors, bpp, img) in enumerate(icons, 1):
        res[RT_ICON][n] = img
        grp += struct.pack('<BBBBHHIH', w, h, colors, 0, 1, bpp, len(img), n)
    res[RT_GROUP_ICON][1] = bytes(grp)
    section, relocs = build_rsrc(res)
    open(out, 'wb').write(coff(section, relocs))
    print(f'{out}: {len(icons)} icon sizes, version {".".join(map(str, VERSION))}, manifest')


# ---------- reading them back from an .exe ----------
def check(exe):
    d = open(exe, 'rb').read()
    pe = struct.unpack_from('<I', d, 0x3C)[0]
    assert d[pe:pe + 4] == b'PE\0\0', 'not a PE file'
    machine, nsec, _, _, _, optsize, _ = struct.unpack_from('<HHIIIHH', d, pe + 4)
    opt = pe + 24
    magic = struct.unpack_from('<H', d, opt)[0]
    assert magic == 0x20B, 'not PE32+'
    subsystem = struct.unpack_from('<H', d, opt + 68)[0]
    rva, size = struct.unpack_from('<II', d, opt + 112 + 2 * 8)     # data directory 2: resources
    secs = []
    for i in range(nsec):
        s = opt + optsize + 40 * i
        name, vsize, va, rawsize, rawptr = struct.unpack_from('<8sIIII', d, s)
        secs.append((name.rstrip(b'\0').decode(), va, max(vsize, rawsize), rawptr))

    def fo(r):
        for _, va, sz, ptr in secs:
            if va <= r < va + sz:
                return ptr + r - va
        raise ValueError('rva outside sections')

    base = fo(rva)
    found = {}

    def walk(at, level, path):
        named, ids = struct.unpack_from('<HH', d, base + at + 12)
        for e in range(named + ids):
            name, off = struct.unpack_from('<II', d, base + at + 16 + 8 * e)
            if off & 0x80000000:
                walk(off & 0x7FFFFFFF, level + 1, path + [name])
            else:
                drva, dsize = struct.unpack_from('<II', d, base + off)
                found[tuple(path + [name])] = d[fo(drva):fo(drva) + dsize]

    walk(0, 0, [])
    kinds = {k[0] for k in found}
    grp = next(v for k, v in found.items() if k[0] == RT_GROUP_ICON)
    n = struct.unpack_from('<H', grp, 4)[0]
    sizes = []
    for i in range(n):
        w, h, _, _, _, bpp, ln, iid = struct.unpack_from('<BBBBHHIH', grp, 6 + 14 * i)
        img = next(v for k, v in found.items() if k[0] == RT_ICON and k[1] == iid)
        assert len(img) == ln, 'icon size mismatch'
        assert img[:8] == b'\x89PNG\r\n\x1a\n' or struct.unpack_from('<I', img, 0)[0] == 40, 'icon image is neither PNG nor BMP'
        sizes.append(w or 256)
    ver = next(v for k, v in found.items() if k[0] == RT_VERSION)
    man = next(v for k, v in found.items() if k[0] == RT_MANIFEST)
    import xml.dom.minidom
    xml.dom.minidom.parseString(man)      # must be well-formed, or Windows refuses to start the program
    texts = {k: (utf16z(v)[:-2] in ver) for k, v in STRINGS.items()}
    sig = struct.unpack_from('<I', ver, 40)[0] if len(ver) > 44 else 0
    print(f'{exe}: machine 0x{machine:x}, subsystem {subsystem} ({"GUI" if subsystem == 2 else "console"}), '
          f'resource types {sorted(kinds)}, icon sizes {sorted(sizes)}, version strings {all(texts.values())}, '
          f'fixed info signature 0x{sig:08x}, manifest {len(man)} bytes')
    assert machine == 0x8664 and subsystem == 2 and {RT_ICON, RT_GROUP_ICON, RT_VERSION, RT_MANIFEST} <= kinds and all(texts.values())
    assert sig == 0xFEEF04BD, 'version block misaligned'
    return True


if __name__ == '__main__':
    if sys.argv[1] == 'make':
        make(sys.argv[2], sys.argv[3])
    else:
        check(sys.argv[2])
