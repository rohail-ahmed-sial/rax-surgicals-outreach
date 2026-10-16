"""Finding leads:
- Google Maps (Places API) search, in several places at once (a queue that runs one search after another),
- a list of websites or email addresses pasted in, a CSV or Excel (.xlsx) file with a column-mapping preview,
- reading each company's website for public business emails and a short text,
- checking that the email's domain takes email (MX record), and judging fit with AI (or keywords without AI).
Long work runs in the background and reports progress."""
import csv, io, json, os, re, ssl, threading, time, html, zipfile, urllib.request, urllib.error, urllib.parse, urllib.robotparser
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from . import db, ai, dnscheck

PLACES_BASE = os.environ.get('RAX_PLACES_BASE', 'https://places.googleapis.com')
UA = 'Mozilla/5.0 (compatible; RAXSurgicalsOutreach/1.0; business contact lookup)'
CTX = ssl.create_default_context()


# ---------- background jobs ----------
def start_job(kind, total, fn):
    jid = db.x('INSERT INTO jobs(kind, status, total, created_at, message) VALUES (?, ?, ?, ?, ?)', (kind, 'running', total, db.now(), ''))

    def progress(done=None, message=None, total=None):
        sets, args = [], []
        if done is not None: sets.append('done=?'); args.append(done)
        if message is not None: sets.append('message=?'); args.append(str(message)[:500])
        if total is not None: sets.append('total=?'); args.append(total)
        if sets: db.x(f"UPDATE jobs SET {', '.join(sets)} WHERE id=?", (*args, jid))

    def run():
        try:
            msg = fn(progress)
            db.x('UPDATE jobs SET status=?, finished_at=?, message=COALESCE(?, message) WHERE id=?', ('done', db.now(), msg, jid))
        except Exception as e:  # noqa
            db.log(f'{kind} job failed: {e}', 'error')
            db.x('UPDATE jobs SET status=?, finished_at=?, message=? WHERE id=?', ('failed', db.now(), str(e)[:500], jid))
    threading.Thread(target=run, daemon=True).start()
    return jid


# ---------- helpers ----------
def domain_of(url):
    if not url:
        return ''
    if '://' not in url:
        url = 'http://' + url
    try:
        host = urllib.parse.urlsplit(url).hostname or ''
    except ValueError:
        return ''
    return host.lower().removeprefix('www.')


def norm_url(url):
    url = (url or '').strip()
    if url and '://' not in url:
        url = 'https://' + url
    return url


EMAIL_FULL = re.compile(r'[^@\s<>,;"]+@[^@\s<>,;"]+\.[a-z]{2,24}', re.I)


def valid_email(e):
    return bool(e) and bool(EMAIL_FULL.fullmatch(e.strip()))


def find_duplicate(domain=None, place_id=None, email=None, company=None, country=None):
    if place_id:
        r = db.q('SELECT id FROM leads WHERE place_id=?', (place_id,), one=True)
        if r: return r['id']
    if domain:
        r = db.q('SELECT id FROM leads WHERE domain=?', (domain,), one=True)
        if r: return r['id']
    if email:
        r = db.q('SELECT id FROM leads WHERE lower(email)=?', (email.lower(),), one=True)
        if r: return r['id']
    if company and not domain:
        r = db.q("SELECT id FROM leads WHERE lower(company)=? AND COALESCE(lower(country),'')=?", (company.lower(), (country or '').lower()), one=True)
        if r: return r['id']
    return None


def add_lead(d, source):
    website = norm_url(d.get('website'))
    domain = domain_of(website)
    email = (d.get('email') or '').strip().lower()
    if email and not valid_email(email):
        email = ''
    if find_duplicate(domain, d.get('place_id'), email, d.get('company'), d.get('country')):
        return None
    emails = [email] if email else []
    return db.x('''INSERT INTO leads(company, website, domain, country, city, address, phone, source, search_query, place_id,
                   emails, email, contact_name, crawl_status, status, notes, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                ((d.get('company') or '').strip()[:200] or domain or email, website, domain, (d.get('country') or '').strip(),
                 (d.get('city') or '').strip(), d.get('address') or '', d.get('phone') or '', source, d.get('search_query') or '',
                 d.get('place_id'), json.dumps(emails), email, (d.get('contact_name') or '').strip(),
                 'pending' if website else 'no_website', 'new', d.get('notes') or '', db.now(), db.now()))


# ---------- Google Maps search (a queue: one search at a time) ----------
_runner_lock = threading.Lock()
_runner = None


def queue_searches(query, locations, max_results=60, auto_check=True):
    locs = [l.strip() for l in (locations or []) if l and l.strip()] or ['']
    ids = []
    for loc in dict.fromkeys(locs):
        ids.append(db.x('INSERT INTO searches(query, location, max, status, created_at, auto_check) VALUES (?,?,?,?,?,?)',
                        (query.strip(), loc, max_results, 'queued', db.now(), 1 if auto_check else 0)))
    _ensure_runner()
    return ids


def _ensure_runner():
    global _runner
    with _runner_lock:
        if _runner and _runner.is_alive():
            return
        _runner = threading.Thread(target=_run_queue, daemon=True)
        _runner.start()


def _run_queue():
    while True:
        s = db.q("SELECT * FROM searches WHERE status='queued' ORDER BY id LIMIT 1", one=True)
        if not s:
            return
        db.x("UPDATE searches SET status='running' WHERE id=?", (s['id'],))
        try:
            found, added, ids = places_search(s['query'], s['location'], s['max'] or 60, search_id=s['id'])
            db.x("UPDATE searches SET status='done', found=?, added=?, finished_at=? WHERE id=?", (found, added, db.now(), s['id']))
            if ids and s['auto_check']:
                process_leads(ids)
        except Exception as e:  # noqa
            code = getattr(e, 'code', '') or ''
            db.x("UPDATE searches SET status='failed', error=?, finished_at=? WHERE id=?", (code or str(e)[:400], db.now(), s['id']))
            db.log(f'Google Maps search failed: {e}', 'error')
            if code in ('places_no_key', 'places_bad_key', 'places_api_off', 'places_billing'):
                db.x("UPDATE searches SET status='failed', error='stopped_key', finished_at=? WHERE status='queued'", (db.now(),))


def recover_searches():
    """After a restart, searches that were running are queued again."""
    db.x("UPDATE searches SET status='queued' WHERE status='running'")
    if db.q("SELECT 1 FROM searches WHERE status='queued' LIMIT 1", one=True):
        _ensure_runner()


def places_error(code, detail):
    d = detail.lower()
    if code in (400, 403) and ('api key' in d or 'api_key' in d or 'permission' in d):
        if 'not been used' in d or 'disabled' in d or 'service_disabled' in d:
            return 'places_api_off'
        if 'billing' in d:
            return 'places_billing'
        return 'places_bad_key'
    if 'billing' in d:
        return 'places_billing'
    if code == 429:
        return 'places_quota'
    return 'places_error'


class PlacesError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _places_call(key, body):
    req = urllib.request.Request(PLACES_BASE + '/v1/places:searchText', data=json.dumps(body).encode(), method='POST', headers={
        'Content-Type': 'application/json', 'X-Goog-Api-Key': key,
        'X-Goog-FieldMask': 'places.id,places.displayName,places.formattedAddress,places.websiteUri,'
                            'places.internationalPhoneNumber,places.addressComponents,places.businessStatus,nextPageToken'})
    try:
        with urllib.request.urlopen(req, timeout=30, context=CTX) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors='replace')[:400]
        raise PlacesError(places_error(e.code, detail), f'Google Places error {e.code}: {detail}')
    except (urllib.error.URLError, OSError) as e:
        raise PlacesError('network', f'Could not reach Google: {e}')
    db.x("INSERT INTO usage(at, kind, model) VALUES (?, 'places', 'text_search')", (db.now(),))
    return data


def places_search(query, location, max_results=60, progress=None, search_id=None):
    key = (db.get('google_places_api_key') or '').strip()
    if not key:
        raise PlacesError('places_no_key', 'Add a Google Places API key in Settings first.')
    text = f'{query} in {location}' if location else query
    added = seen = 0
    ids = []
    token = None
    for page in range(3):
        body = {'textQuery': text, 'pageSize': 20}
        if token: body['pageToken'] = token
        data = _places_call(key, body)
        for p in data.get('places', []):
            seen += 1
            if p.get('businessStatus') in ('CLOSED_PERMANENTLY',):
                continue
            comps = p.get('addressComponents', [])
            country = next((c.get('longText') for c in comps if 'country' in c.get('types', [])), '') or location.split(',')[-1].strip()
            city = next((c.get('longText') for c in comps if 'locality' in c.get('types', [])), '')
            lid = add_lead({'company': (p.get('displayName') or {}).get('text', ''), 'website': p.get('websiteUri', ''),
                            'address': p.get('formattedAddress', ''), 'phone': p.get('internationalPhoneNumber', ''),
                            'country': country, 'city': city, 'place_id': p.get('id'), 'search_query': text}, 'google_maps')
            if lid:
                added += 1
                ids.append(lid)
            if progress: progress(done=seen, message=f'{seen} found, {added} new')
            if search_id: db.x('UPDATE searches SET found=?, added=? WHERE id=?', (seen, added, search_id))
            if seen >= max_results: break
        token = data.get('nextPageToken')
        if not token or seen >= max_results:
            break
        time.sleep(2)
    db.log(f'Google Maps search "{text}": {seen} found, {added} new leads')
    return seen, added, ids


def test_places():
    key = (db.get('google_places_api_key') or '').strip()
    if not key:
        raise PlacesError('places_no_key', 'No key')
    data = _places_call(key, {'textQuery': 'surgical instruments distributor in Germany', 'pageSize': 1})
    return len(data.get('places', []))


# ---------- search ideas without AI ----------
LANG_OF = {
    'germany': 'de', 'deutschland': 'de', 'austria': 'de', 'switzerland': 'de',
    'france': 'fr', 'belgium': 'fr', 'morocco': 'fr', 'tunisia': 'fr', 'algeria': 'fr',
    'spain': 'es', 'mexico': 'es', 'colombia': 'es', 'argentina': 'es', 'chile': 'es', 'peru': 'es',
    'italy': 'it', 'netherlands': 'nl', 'portugal': 'pt', 'brazil': 'pt', 'turkey': 'tr', 'türkiye': 'tr', 'poland': 'pl',
    'saudi arabia': 'ar', 'united arab emirates': 'ar', 'uae': 'ar', 'egypt': 'ar', 'qatar': 'ar', 'kuwait': 'ar', 'oman': 'ar',
    'bahrain': 'ar', 'jordan': 'ar', 'iraq': 'ar',
}
LOCAL_QUERIES = {
    'de': ['Medizinischer Großhandel', 'Chirurgische Instrumente', 'Praxisbedarf', 'Dentalbedarf', 'Medizintechnik Händler', 'Kosmetikbedarf Großhandel', 'Tierarztbedarf'],
    'fr': ['grossiste matériel médical', 'instruments chirurgicaux', 'fournitures dentaires', 'distributeur matériel médical', 'fournitures esthétique professionnelle', 'matériel vétérinaire'],
    'es': ['instrumental quirúrgico', 'distribuidor material quirúrgico', 'suministros médicos mayorista', 'depósito dental', 'suministros veterinarios', 'insumos de manicura'],
    'it': ['strumenti chirurgici', 'forniture mediche ingrosso', 'articoli sanitari', 'forniture dentali', 'forniture veterinarie', 'forniture estetica professionale'],
    'nl': ['medische groothandel', 'chirurgische instrumenten', 'tandheelkundige groothandel', 'dierenartsbenodigdheden', 'pedicurebenodigdheden'],
    'pt': ['material cirúrgico', 'distribuidora de produtos hospitalares', 'instrumentos cirúrgicos', 'dental distribuidora', 'produtos veterinários', 'material para manicure'],
    'tr': ['cerrahi alet', 'medikal malzeme toptan', 'dental depo', 'veteriner malzemeleri', 'medikal firma'],
    'pl': ['narzędzia chirurgiczne', 'hurtownia medyczna', 'hurtownia stomatologiczna', 'artykuły weterynaryjne'],
    'ar': ['مستلزمات طبية', 'أدوات جراحية', 'مستلزمات أسنان', 'معدات طبية'],
}
ENGLISH_QUERIES = ['surgical instruments distributor', 'medical supplies wholesaler', 'hospital supply company', 'dental supply company',
                   'veterinary supplies distributor', 'beauty supply wholesaler', 'podiatry supplies', 'medical equipment importer']


def suggest_queries(location, focus=''):
    if ai.available() and (location or '').strip():
        try:
            out = ai.suggest_queries(location, focus)
            if out:
                return {'queries': out, 'by': 'ai'}
        except Exception as e:  # noqa
            db.log(f'AI search ideas failed: {e}', 'warn')
    country = (location or '').split(',')[-1].strip().lower()
    local = LOCAL_QUERIES.get(LANG_OF.get(country, ''), [])
    return {'queries': local + ENGLISH_QUERIES[:8 - min(4, len(local))] if local else ENGLISH_QUERIES, 'by': 'list'}


# ---------- pasted websites or emails ----------
TOKEN_SPLIT = re.compile(r'[\s,;|]+')


def import_pasted(text, country=''):
    """One website or email per line (commas and spaces work too). Returns ids of new leads."""
    added, skipped, ids = 0, 0, []
    for tok in TOKEN_SPLIT.split(text or ''):
        tok = tok.strip().strip('<>()[]"\'').rstrip('.')
        if not tok:
            continue
        if tok.lower().startswith('mailto:'):
            tok = tok[7:]
        if '@' in tok:
            if not valid_email(tok):
                skipped += 1; continue
            dom = tok.split('@')[-1].lower()
            web = '' if dom in dnscheck.FREE_MAIL else dom
            lid = add_lead({'email': tok, 'website': web, 'company': dom if web else tok, 'country': country}, 'pasted')
        else:
            dom = domain_of(tok)
            if not dom or '.' not in dom or len(dom) < 4:
                skipped += 1; continue
            lid = add_lead({'website': tok, 'company': dom, 'country': country}, 'pasted')
        if lid: added += 1; ids.append(lid)
        else: skipped += 1
    db.log(f'Pasted list: {added} added, {skipped} skipped')
    return {'added': added, 'skipped': skipped, 'ids': ids}


# ---------- CSV and Excel files ----------
ALIASES = {'company': ['company', 'company name', 'name', 'business', 'business name', 'organisation', 'organization', 'firma', 'unternehmen',
                       'exhibitor', 'account', 'account name', 'société', 'empresa'],
           'website': ['website', 'url', 'web', 'site', 'domain', 'homepage', 'webseite', 'internet', 'web site', 'www'],
           'email': ['email', 'e-mail', 'mail', 'email address', 'e-mail address', 'emails', 'contact email'],
           'country': ['country', 'land', 'nation', 'pays', 'país', 'country/region'],
           'city': ['city', 'town', 'ort', 'stadt', 'ville', 'ciudad'],
           'phone': ['phone', 'telephone', 'tel', 'mobile', 'whatsapp', 'telefon', 'phone number'],
           'contact_name': ['contact', 'contact name', 'person', 'full name', 'buyer', 'contact person', 'ansprechpartner', 'first name'],
           'address': ['address', 'street', 'adresse', 'dirección'],
           'notes': ['notes', 'note', 'comment', 'comments', 'remarks', 'description']}
FIELDS = list(ALIASES)


def _col_index(ref):
    n = 0
    for ch in ref:
        if ch.isalpha():
            n = n * 26 + (ord(ch.upper()) - 64)
        else:
            break
    return max(0, n - 1)


def xlsx_rows(data, max_rows=50000):
    """The first worksheet of an .xlsx file as rows of text (no extra packages)."""
    M = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError('bad_file')
    names = set(z.namelist())
    shared = []
    if 'xl/sharedStrings.xml' in names:
        for si in ET.fromstring(z.read('xl/sharedStrings.xml')).iter(M + 'si'):
            shared.append(''.join(t.text or '' for t in si.iter(M + 't')))
    path = 'xl/worksheets/sheet1.xml'
    try:
        wb = ET.fromstring(z.read('xl/workbook.xml'))
        first = next(wb.iter(M + 'sheet'))
        rid = first.get(R + 'id')
        rels = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        for rel in rels:
            if rel.get('Id') == rid:
                t = rel.get('Target', '')
                path = t.lstrip('/') if t.startswith('/') else 'xl/' + t
    except (KeyError, StopIteration, ET.ParseError):
        pass
    if path not in names:
        sheets = sorted(n for n in names if n.startswith('xl/worksheets/sheet'))
        if not sheets:
            raise ValueError('bad_file')
        path = sheets[0]
    rows = []
    for row in ET.fromstring(z.read(path)).iter(M + 'row'):
        cells = {}
        for i, c in enumerate(row.iter(M + 'c')):
            ref = c.get('r') or ''
            col = _col_index(ref) if ref else i
            t = c.get('t')
            v = c.find(M + 'v')
            if t == 's':
                val = shared[int(v.text)] if v is not None and v.text and v.text.isdigit() and int(v.text) < len(shared) else ''
            elif t == 'inlineStr':
                val = ''.join(x.text or '' for x in c.iter(M + 't'))
            elif t == 'b':
                val = 'TRUE' if v is not None and v.text == '1' else 'FALSE'
            else:
                val = (v.text or '') if v is not None else ''
                if re.fullmatch(r'-?\d+\.0', val):
                    val = val[:-2]
            cells[col] = val.strip()
        if cells:
            rows.append([cells.get(i, '') for i in range(max(cells) + 1)])
        if len(rows) >= max_rows:
            break
    return rows


def text_rows(data):
    for enc in ('utf-8-sig', 'cp1252', 'latin-1'):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    try:
        dialect = csv.Sniffer().sniff(text[:4000], delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel
    return [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), dialect)]


def file_rows(name, data):
    n = (name or '').lower()
    if n.endswith('.xls'):
        raise ValueError('old_excel')
    if n.endswith(('.xlsx', '.xlsm')) or data[:2] == b'PK':
        return xlsx_rows(data)
    return text_rows(data)


def guess_mapping(headers):
    head = [h.strip().lower() for h in headers]
    m = {}
    for field, names in ALIASES.items():
        for i, h in enumerate(head):
            if (h in names or h.replace('_', ' ') in names) and i not in m.values():
                m[field] = i
                break
    return m


def preview(name, data):
    rows = [r for r in file_rows(name, data) if any(c.strip() for c in r)]
    if not rows:
        raise ValueError('empty_file')
    headers = rows[0]
    width = max(len(r) for r in rows[:200])
    headers = headers + [''] * (width - len(headers))
    return {'headers': headers, 'sample': [r + [''] * (width - len(r)) for r in rows[1:9]], 'rows': len(rows) - 1,
            'mapping': guess_mapping(headers)}


def import_rows(name, data, mapping, default_country=''):
    rows = [r for r in file_rows(name, data) if any(c.strip() for c in r)]
    mapping = {f: int(i) for f, i in (mapping or {}).items() if f in FIELDS and str(i).lstrip('-').isdigit() and int(i) >= 0}
    if not any(f in mapping for f in ('company', 'website', 'email')):
        raise ValueError('need_column')
    added = skipped = 0
    ids = []
    for r in rows[1:]:
        d = {f: (r[i].strip() if i < len(r) else '') for f, i in mapping.items()}
        if not any(d.values()):
            continue
        if not d.get('country'):
            d['country'] = default_country
        if d.get('email'):
            first = EMAIL_FULL.search(d['email'])          # cells like "info@x.com; sales@x.com"
            d['email'] = first.group(0) if first else ''
        if not d.get('company'):
            d['company'] = domain_of(d.get('website')) or (d.get('email') or '').split('@')[-1]
        lid = add_lead(d, 'import')
        if lid: added += 1; ids.append(lid)
        else: skipped += 1
    db.log(f'Import {name}: {added} added, {skipped} skipped (duplicates or empty)')
    return {'added': added, 'skipped': skipped, 'ids': ids}


def import_csv(text, default_country=''):
    """Version 1 style: CSV text with column names in the first row."""
    data = (text or '').encode()
    rows = [r for r in text_rows(data) if any(c.strip() for c in r)]
    if not rows:
        return {'added': 0, 'skipped': 0, 'ids': []}
    m = guess_mapping(rows[0])
    if not any(f in m for f in ('company', 'website', 'email')):
        raise ValueError('The first row must have column names, e.g. company, website, email, country.')
    return import_rows('list.csv', data, m, default_country)


def export_csv(rows):
    out = io.StringIO()
    cols = ['company', 'website', 'email', 'email_status', 'contact_name', 'country', 'city', 'phone', 'fit', 'score', 'category',
            'status', 'stage', 'deal_value', 'next_action', 'next_action_date', 'ai_reason', 'source', 'created_at']
    w = csv.writer(out)
    w.writerow(cols)
    for r in rows:
        w.writerow([r.get(c) if r.get(c) is not None else '' for c in cols])
    return '﻿' + out.getvalue()        # BOM so Excel shows accented names correctly


# ---------- reading a company website ----------
class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.text, self.mailto, self.cf = [], [], [], []
        self.site_name = ''
        self._skip = 0
        self._a = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ('script', 'style', 'noscript', 'svg'):
            self._skip += 1
        if tag == 'meta' and (a.get('property') or '').lower() == 'og:site_name' and a.get('content'):
            self.site_name = a['content'].strip()
        if tag == 'a' and a.get('href'):
            href = a['href'].strip()
            if href.lower().startswith('mailto:'):
                self.mailto.append(urllib.parse.unquote(href[7:].split('?')[0]))
            else:
                self._a = [href, '']
                self.links.append(self._a)
        if a.get('data-cfemail'):
            self.cf.append(a['data-cfemail'])

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript', 'svg') and self._skip:
            self._skip -= 1
        if tag == 'a':
            self._a = None

    def handle_data(self, data):
        if self._skip:
            return
        if self._a is not None:
            self._a[1] += data
        s = data.strip()
        if s:
            self.text.append(s)


def _cf_decode(h):
    try:
        k = int(h[:2], 16)
        return ''.join(chr(int(h[i:i + 2], 16) ^ k) for i in range(2, len(h), 2))
    except ValueError:
        return ''


EMAIL_RE = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}')
OBFUSCATED_RE = re.compile(r'([A-Za-z0-9._%+-]+)\s*[\[\(]\s*at\s*[\]\)]\s*([A-Za-z0-9-]+)\s*[\[\(]\s*dot\s*[\]\)]\s*([A-Za-z]{2,24})', re.I)
BAD_EMAIL = re.compile(r'\.(png|jpe?g|gif|webp|svg|css|js)$|^(no-?reply|donotreply|privacy|datenschutz|gdpr|abuse|postmaster|webmaster|jobs?|careers?|hr|bewerbung|recruit)'
                       r'|example\.|sentry|wixpress|domain\.com|email\.com|yourdomain|@\d', re.I)
GOOD_LINK = re.compile(r'contact|kontakt|about|ueber|über|impressum|imprint|team|company|unternehmen|contacto|contatti|nous|chi-siamo|sobre|over-ons|wholesale|distribut', re.I)
EMAIL_RANK = ['purchas', 'procure', 'buying', 'einkauf', 'import', 'sales', 'vertrieb', 'order', 'info', 'contact', 'kontakt', 'office', 'hello', 'mail', 'service', 'support']
TITLE_SPLIT = re.compile(r'\s+[|–—\-:·•]\s+')


def rank_email(e, domain):
    local, _, host = e.partition('@')
    same = host.lower().removeprefix('www.') == domain or host.lower().endswith('.' + domain)
    pos = next((i for i, k in enumerate(EMAIL_RANK) if k in local.lower()), len(EMAIL_RANK) - 3)  # a person's name ranks like "info"
    return (0 if same else 1, pos)


def _fetch(url, max_bytes=1_500_000, any_type=False):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'text/html,*/*;q=0.5', 'Accept-Language': 'en,*;q=0.5'})
    with urllib.request.urlopen(req, timeout=15, context=CTX) as r:
        if not any_type and 'html' not in (r.headers.get('Content-Type') or 'text/html'):
            return r.geturl(), ''
        raw = r.read(max_bytes)
        cs = r.headers.get_content_charset() or 'utf-8'
        return r.geturl(), raw.decode(cs, errors='replace')


def _robots(url):
    rp = urllib.robotparser.RobotFileParser()
    parts = urllib.parse.urlsplit(url)
    try:
        _, txt = _fetch(f'{parts.scheme}://{parts.netloc}/robots.txt', 200_000, any_type=True)
        rp.parse(txt.splitlines())
    except Exception:
        rp.parse([])
    return rp


def _looks_like_domain(name, domain):
    n = (name or '').strip().lower()
    return not n or n == domain or n == 'www.' + domain or n.removeprefix('www.') == domain or ('@' in n and ' ' not in n)


def _name_from(site_name, title):
    if site_name:
        return site_name[:80]
    if not title:
        return ''
    parts = [p.strip() for p in TITLE_SPLIT.split(html.unescape(title).strip()) if p.strip()]
    if not parts:
        return ''
    generic = re.compile(r'^(home|homepage|startseite|welcome|accueil|inicio|start)$', re.I)
    parts = [p for p in parts if not generic.match(p)] or parts
    return parts[0][:80]


def crawl(lead_id, max_pages=6):
    lead = db.q('SELECT * FROM leads WHERE id=?', (lead_id,), one=True)
    if not lead or not lead.get('website'):
        db.x("UPDATE leads SET crawl_status='no_website', updated_at=? WHERE id=?", (db.now(), lead_id))
        return lead
    start = norm_url(lead['website'])
    domain = domain_of(start)
    emails, texts, seen = set(), [], set()
    note = ''
    first_title = site_name = ''
    rp = _robots(start)
    queue = [start]
    pages = 0
    try:
        while queue and pages < max_pages:
            url = queue.pop(0)
            key = url.split('#')[0].rstrip('/')
            if key in seen:
                continue
            seen.add(key)
            if not rp.can_fetch(UA, url):
                note = 'some pages blocked by robots.txt'
                continue
            try:
                final, page = _fetch(url)
            except Exception as e:  # noqa
                if pages == 0 and url == start and start.startswith('https://'):
                    queue.insert(0, 'http://' + start[8:]); continue
                if pages == 0: raise
                continue
            pages += 1
            p = _Page()
            try:
                p.feed(page)
            except Exception:
                pass
            for m in p.mailto: emails.add(m.strip())
            for h in p.cf: emails.add(_cf_decode(h))
            body = ' '.join(p.text)
            for m in EMAIL_RE.findall(html.unescape(page)): emails.add(m)
            for a, b, c in OBFUSCATED_RE.findall(body): emails.add(f'{a}@{b}.{c}')
            title = re.search(r'<title[^>]*>(.*?)</title>', page, re.S | re.I)
            if pages == 1:
                first_title = title.group(1).strip() if title else ''
                site_name = p.site_name
            if len(' '.join(texts)) < 7000:
                texts.append(f"[{urllib.parse.urlsplit(final).path or '/'}] " + (html.unescape(title.group(1).strip()) + ' | ' if title else '') + body[:3000])
            if pages == 1:   # pick contact/about pages from the first page
                cands = []
                for href, label in p.links:
                    full = urllib.parse.urljoin(final, href)
                    if domain_of(full) != domain or not full.startswith('http'):
                        continue
                    if GOOD_LINK.search(href) or GOOD_LINK.search(label):
                        cands.append(full)
                queue.extend(dict.fromkeys(cands))
    except Exception as e:  # noqa
        db.x("UPDATE leads SET crawl_status='failed', crawl_note=?, updated_at=? WHERE id=?", (f'Website did not open: {str(e)[:150]}', db.now(), lead_id))
        return db.q('SELECT * FROM leads WHERE id=?', (lead_id,), one=True)
    clean = sorted({e.strip().strip('.').lower() for e in emails if e and EMAIL_RE.fullmatch(e.strip().strip('.')) and not BAD_EMAIL.search(e.strip())},
                   key=lambda e: rank_email(e, domain))
    keep = set(db.jloads(lead['emails'], []))
    allm = clean + [e for e in keep if e not in clean]
    best = lead['email'] or (allm[0] if allm else '')
    company = lead['company']
    if _looks_like_domain(company, domain):
        company = _name_from(site_name, first_title) or company
    db.x('UPDATE leads SET company=?, emails=?, email=?, site_text=?, crawl_status=?, crawl_note=?, updated_at=? WHERE id=?',
         (company, json.dumps(allm[:15]), best, '\n'.join(texts)[:9000], 'ok',
          (note or f"{pages} page{'s' if pages != 1 else ''} read, {len(clean)} email{'s' if len(clean) != 1 else ''} found"), db.now(), lead_id))
    return db.q('SELECT * FROM leads WHERE id=?', (lead_id,), one=True)


# ---------- checking the email address ----------
def verify_email(lead_id):
    """email_status: valid (domain takes email), free (gmail/outlook...), no_mx (domain takes no email), invalid, unknown."""
    lead = db.q('SELECT email FROM leads WHERE id=?', (lead_id,), one=True)
    e = (lead or {}).get('email') or ''
    if not e:
        status = None
    elif not valid_email(e):
        status = 'invalid'
    else:
        dom = e.split('@')[-1].lower()
        if dom in dnscheck.FREE_MAIL:
            status = 'free'
        else:
            ok = dnscheck.mx_ok(dom)
            status = 'valid' if ok else ('no_mx' if ok is False else 'unknown')
    db.x('UPDATE leads SET email_status=? WHERE id=?', (status, lead_id))
    return status


def qualify(lead_id):
    lead = db.q('SELECT * FROM leads WHERE id=?', (lead_id,), one=True)
    if not lead:
        return None
    try:
        r = ai.qualify(lead) if ai.available() else ai.qualify_rules(lead)
    except (ai.NoAI, ai.AIError) as e:
        if isinstance(e, ai.AIError):
            db.log(f"AI could not check {lead['company']} ({e.code}); used the keyword check", 'warn')
        r = ai.qualify_rules(lead)
    contact = r.pop('contact_name', '') or lead.get('contact_name') or ''
    status = lead['status']
    usable = bool(lead.get('email')) and lead.get('email_status') not in ('no_mx', 'invalid')
    if status in ('new', 'ready', 'rejected'):
        status = 'rejected' if r['fit'] == 'no' else ('ready' if usable else 'new')
    db.x('UPDATE leads SET fit=?, score=?, category=?, ai_reason=?, language=COALESCE(?, language), contact_name=?, status=?, updated_at=? WHERE id=?',
         (r['fit'], r['score'], r['category'], r['ai_reason'], r.get('language'), contact, status, db.now(), lead_id))
    return r


def process_leads(ids, do_crawl=True, do_qualify=True):
    """Read websites, check emails and judge fit for many leads, a few websites at a time."""
    ids = list(ids)

    def work(progress):
        done = [0]
        lock = threading.Lock()
        it = iter(ids)

        def worker():
            while True:
                with lock:
                    lid = next(it, None)
                if lid is None:
                    return
                try:
                    if do_crawl:
                        lead = db.q('SELECT crawl_status FROM leads WHERE id=?', (lid,), one=True)
                        if lead and lead['crawl_status'] in ('pending', 'failed', 'ok'):
                            crawl(lid)
                    if db.get('mx_check_on') == '1':
                        verify_email(lid)
                    if do_qualify:
                        qualify(lid)
                except Exception as e:  # noqa
                    db.log(f'Lead {lid}: {e}', 'error')
                with lock:
                    done[0] += 1
                    progress(done=done[0], message=f'{done[0]} of {len(ids)} leads checked')
        ts = [threading.Thread(target=worker, daemon=True) for _ in range(min(4, len(ids)) or 1)]
        for t in ts: t.start()
        for t in ts: t.join()
        good = db.q(f"SELECT COUNT(*) n FROM leads WHERE fit='good' AND id IN ({','.join('?' * len(ids))})", ids, one=True)['n'] if ids else 0
        db.log(f'Checked {len(ids)} leads: {good} good fit')
        return f'{len(ids)} leads checked, {good} good fit'
    return start_job('check_leads', len(ids), work)


def verify_leads(ids):
    ids = list(ids)

    def work(progress):
        counts = {}
        for n, lid in enumerate(ids, 1):
            s = verify_email(lid) or 'none'
            counts[s] = counts.get(s, 0) + 1
            l = db.q('SELECT status, fit, email FROM leads WHERE id=?', (lid,), one=True)
            if l and s in ('no_mx', 'invalid') and l['status'] == 'ready':
                db.x("UPDATE leads SET status='new' WHERE id=?", (lid,))
            elif l and s in ('valid', 'free', 'unknown') and l['status'] == 'new' and l['fit'] in ('good', 'maybe') and l['email']:
                db.x("UPDATE leads SET status='ready' WHERE id=?", (lid,))
            progress(done=n, message=f'{n} of {len(ids)} checked')
        return ', '.join(f'{v} {k}' for k, v in counts.items())
    return start_job('verify', len(ids), work)
