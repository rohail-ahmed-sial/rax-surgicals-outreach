"""DNS lookups over HTTPS (works on any computer without extra packages):
- does a domain accept email at all (MX record)? Used before the first email to a company, to avoid bounces;
- is the sender's own domain set up so emails do not land in spam (SPF, DKIM, DMARC)?"""
import json, os, ssl, urllib.request, urllib.parse, urllib.error, datetime as dt
from . import db

PROVIDERS = [p for p in [os.environ.get('RAX_DOH_BASE'), 'https://dns.google/resolve', 'https://cloudflare-dns.com/dns-query'] if p]
CTX = ssl.create_default_context()
TYPES = {'A': 1, 'CNAME': 5, 'MX': 15, 'TXT': 16, 'AAAA': 28}
FREE_MAIL = {'gmail.com', 'googlemail.com', 'outlook.com', 'hotmail.com', 'live.com', 'yahoo.com', 'icloud.com', 'aol.com',
             'proton.me', 'protonmail.com', 'zoho.com', 'yandex.com', 'mail.com', 'gmx.com', 'gmx.de', 'web.de'}


class Unreachable(Exception):
    pass


def resolve(name, rtype):
    """Returns (status, [answers]). status 0 = found or empty, 3 = the domain does not exist. Raises Unreachable."""
    last = None
    for base in PROVIDERS:
        url = base + '?' + urllib.parse.urlencode({'name': name, 'type': rtype})
        req = urllib.request.Request(url, headers={'Accept': 'application/dns-json', 'User-Agent': 'RAXSurgicalsOutreach/2'})
        try:
            with urllib.request.urlopen(req, timeout=8, context=CTX) as r:
                data = json.loads(r.read().decode())
        except Exception as e:  # noqa
            last = e
            continue
        want = TYPES[rtype]
        out = []
        for a in data.get('Answer') or []:
            if a.get('type') != want:
                continue
            d = str(a.get('data', ''))
            if rtype == 'TXT':   # "v=spf1 ..." may come split into several quoted parts
                parts = [p for p in d.split('"') if p.strip()] if '"' in d else [d]
                d = ''.join(parts)
            out.append(d.strip())
        return int(data.get('Status', 0)), out
    raise Unreachable(str(last))


def mx_ok(domain, max_age_days=30):
    """True: the domain can receive email. False: it cannot (no such domain, or no mail server).
    None: could not check (no internet or DNS service blocked); then sending is not blocked."""
    domain = (domain or '').strip().lower().strip('.')
    if not domain:
        return None
    row = db.q('SELECT mx_ok, checked_at FROM domains WHERE domain=?', (domain,), one=True)
    if row and row['mx_ok'] is not None and row['checked_at']:
        try:
            age = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(row['checked_at'])
            if age.days < max_age_days:
                return bool(row['mx_ok'])
        except ValueError:
            pass
    try:
        status, mx = resolve(domain, 'MX')
        hosts = [m.split()[-1].strip('.') for m in mx if m.split()]
        if status == 3:
            ok = False
        elif hosts and not any(hosts):     # "0 ." is a null MX: the domain says it takes no email
            ok = False
        elif any(hosts):
            ok = True
        else:
            st, a = resolve(domain, 'A')    # no MX: mail goes to the domain itself if it has an address
            ok = st == 0 and bool(a)
    except Unreachable:
        return None
    db.x('INSERT INTO domains(domain, mx_ok, checked_at) VALUES (?,?,?) ON CONFLICT(domain) DO UPDATE SET mx_ok=excluded.mx_ok, checked_at=excluded.checked_at',
         (domain, 1 if ok else 0, db.now()))
    return ok


DKIM_SELECTORS = ['google', 'selector1', 'selector2', 'zmail', 'default', 'hostingermail1', 'dkim', 'mail', 's1', 'k1']


def check_sender(email_addr):
    """Checks the sender's domain. Each item: {key, status: ok|warn|bad|unknown, code, data}."""
    email_addr = (email_addr or '').strip().lower()
    if '@' not in email_addr:
        return {'domain': '', 'items': [], 'error': 'no_sender'}
    domain = email_addr.split('@')[-1]
    if domain in FREE_MAIL:
        return {'domain': domain, 'free': True, 'items': [{'key': 'free', 'status': 'warn', 'code': 'free_mailbox', 'data': {'domain': domain}}]}
    items = []
    try:
        st, mx = resolve(domain, 'MX')
        if st == 3:
            return {'domain': domain, 'items': [{'key': 'domain', 'status': 'bad', 'code': 'no_domain', 'data': {'domain': domain}}]}
        items.append({'key': 'mx', 'status': 'ok' if mx else 'bad', 'code': 'mx_ok' if mx else 'mx_missing',
                      'data': {'hosts': [m.split()[-1].strip('.') for m in mx][:3]}})
        st, txt = resolve(domain, 'TXT')
        spf = [t for t in txt if t.lower().startswith('v=spf1')]
        if not spf:
            items.append({'key': 'spf', 'status': 'bad', 'code': 'spf_missing', 'data': {}})
        elif len(spf) > 1:
            items.append({'key': 'spf', 'status': 'bad', 'code': 'spf_double', 'data': {'records': spf}})
        else:
            items.append({'key': 'spf', 'status': 'ok', 'code': 'spf_ok', 'data': {'record': spf[0]}})
        st, dm = resolve('_dmarc.' + domain, 'TXT')
        dmarc = [t for t in dm if t.lower().startswith('v=dmarc1')]
        if not dmarc:
            items.append({'key': 'dmarc', 'status': 'warn', 'code': 'dmarc_missing', 'data': {}})
        else:
            pol = next((p.split('=', 1)[1].strip() for p in dmarc[0].replace(' ', '').split(';') if p.lower().startswith('p=')), '')
            items.append({'key': 'dmarc', 'status': 'ok', 'code': 'dmarc_ok', 'data': {'record': dmarc[0], 'policy': pol}})
        found = None
        for sel in DKIM_SELECTORS:
            st, dk = resolve(f'{sel}._domainkey.{domain}', 'TXT')
            if any('p=' in t for t in dk):
                found = sel
                break
            st, cn = resolve(f'{sel}._domainkey.{domain}', 'CNAME')
            if cn:
                found = sel
                break
        items.append({'key': 'dkim', 'status': 'ok' if found else 'warn', 'code': 'dkim_ok' if found else 'dkim_missing',
                      'data': {'selector': found} if found else {}})
    except Unreachable:
        return {'domain': domain, 'items': [{'key': 'net', 'status': 'unknown', 'code': 'dns_unreachable', 'data': {}}]}
    return {'domain': domain, 'items': items}
