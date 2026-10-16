"""End-to-end test of RAX Surgicals Outreach v2 against stand-in services (Linux only: it adds test host names to /etc/hosts).
Run: python3 tests/e2e.py"""
import os, sys, json, time, tempfile, base64, io, email, email.policy, sqlite3, subprocess, threading, http.client
import urllib.request, urllib.error, http.cookiejar, datetime as dt
from email.utils import make_msgid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mocks

M = mocks.start_all()
TMP = tempfile.mkdtemp(prefix='raxo-')
os.environ['RAX_DATA_DIR'] = TMP
os.environ['RAX_NO_WORKER'] = '1'
os.environ['RAX_ANTHROPIC_BASE'] = f"http://127.0.0.1:{M['ai'].server_address[1]}"
os.environ['RAX_PLACES_BASE'] = f"http://127.0.0.1:{M['places'].server_address[1]}"
DOH = f"http://127.0.0.1:{M['doh'].server_address[1]}/resolve"
from app import db, server, worker, mailer, finder, dnscheck, quality  # noqa
dnscheck.PROVIDERS = [DOH]

HOSTS = ['medsupply.test', 'dentalhaus.test', 'sialkotmakers.test', 'deadsite.test', 'csvco.test', 'pasted-one.test', 'nomail.test']
hosts = open('/etc/hosts').read()
missing = [h for h in HOSTS if h not in hosts]
if missing:
    open('/etc/hosts', 'a').write('\n127.0.0.1 ' + ' '.join(missing) + '\n')
SP = M['sites'].server_address[1]
url = lambda h: f'http://{h}:{SP}'
for d in ['medsupply.test', 'dentalhaus.test', 'csvco.test', 'sialkotmakers.test', 'pasted-one.test', 'limit.test', 'raxsurgicals.test', 'xlsxco.test', 'gmail.com']:
    mocks.DNS[(d, 'MX')] = [f'10 mx.{d}.']
mocks.DNS[('nomail.test', 'NX')] = True
mocks.DNS[('raxsurgicals.test', 'TXT')] = ['"v=spf1 include:_spf.google.com ~all"']
mocks.DNS[('google._domainkey.raxsurgicals.test', 'TXT')] = ['"v=DKIM1; k=rsa; p=MIIBIjANBg"']

mocks.SITES['medsupply.test'] = {
    '/': '<html><head><title>MedSupply GmbH — surgical instruments distributor</title></head><body><nav><a href="/contact">Contact us</a></nav>'
         '<h1>Surgical and dental instruments for clinics</h1><p>We are a distributor and wholesale supplier of medical supplies to hospitals.</p>'
         '<script>var x="tracker@sentry.io"</script><img src="logo@2x.png"></body></html>',
    '/contact': '<html><body><h1>Contact</h1><p>Anna Keller, Head of Purchasing</p><a href="mailto:sales@medsupply.test?subject=Hi">Write to sales</a>'
                '<p>General: info@medsupply.test · Careers: jobs@medsupply.test</p>'
                '<a class="__cf_email__" data-cfemail="' + (lambda e, k=0x5a: format(k, '02x') + ''.join(format(ord(c) ^ k, '02x') for c in e))('purchasing@medsupply.test') + '">[email protected]</a>'
                '</body></html>',
    '/robots.txt': 'User-agent: *\nAllow: /\n'}
mocks.SITES['dentalhaus.test'] = {
    '/': '<html><head><title>DentalHaus</title></head><body><h1>Dental und Chirurgie Instrumente</h1><p>Großhandel für Praxisbedarf, medizin.</p>'
         '<a href="/impressum">Impressum</a> <a href="/privat/kontakt">Kontakt intern</a></body></html>',
    '/impressum': '<html><body>Impressum. E-Mail: kontakt [at] dentalhaus [dot] test</body></html>',
    '/privat/kontakt': '<html><body>secret@dentalhaus.test</body></html>',
    '/robots.txt': 'User-agent: *\nDisallow: /privat/\n'}
mocks.SITES['sialkotmakers.test'] = {'/': '<html><body><h1>Surgical instruments manufacturer in Sialkot, Pakistan</h1><a href="/contact">contact</a></body></html>',
                                     '/contact': '<html><body>export@sialkotmakers.test</body></html>'}
mocks.SITES['csvco.test'] = {'/': '<html><body><h1>Beauty supply wholesale: manicure and pedicure instruments</h1></body></html>'}
mocks.SITES['pasted-one.test'] = {'/': '<html><head><meta property="og:site_name" content="Pasted One Medical"><title>Home | Pasted One</title></head>'
                                       '<body><h1>Medical supplies wholesale</h1><a href="mailto:orders@pasted-one.test">mail</a></body></html>'}
mocks.SITES['nomail.test'] = {'/': '<html><body><h1>Surgical instruments distributor</h1><p>orders@nomail.test</p></body></html>'}
mocks.PLACES[:] = [
    {'id': 'p1', 'displayName': {'text': 'MedSupply GmbH'}, 'websiteUri': url('medsupply.test') + '/', 'formattedAddress': 'Hauptstr. 1, Munich, Germany',
     'internationalPhoneNumber': '+49 89 1', 'addressComponents': [{'longText': 'Munich', 'types': ['locality']}, {'longText': 'Germany', 'types': ['country']}]},
    {'id': 'p2', 'displayName': {'text': 'DentalHaus'}, 'websiteUri': url('dentalhaus.test'), 'formattedAddress': 'Berlin',
     'addressComponents': [{'longText': 'Germany', 'types': ['country']}]},
    {'id': 'p3', 'displayName': {'text': 'Sialkot Makers'}, 'websiteUri': url('sialkotmakers.test'), 'addressComponents': []},
    {'id': 'p4', 'displayName': {'text': 'No Web Clinic Supplies'}, 'addressComponents': [{'longText': 'Germany', 'types': ['country']}]},
    {'id': 'p5', 'displayName': {'text': 'Closed Co'}, 'businessStatus': 'CLOSED_PERMANENTLY', 'websiteUri': url('deadsite.test')},
]

ok = fail = 0


def check(cond, name, detail=''):
    global ok, fail
    if cond: ok += 1; print('  pass', name)
    else: fail += 1; print('  FAIL', name, str(detail)[:600])


httpd = server.serve('127.0.0.1', 0, require_login=False)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
PORT = httpd.server_address[1]
BASE = f'http://127.0.0.1:{PORT}'
jar = http.cookiejar.CookieJar(); opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), urllib.request.ProxyHandler({}))


def call(method, path, body=None, hdr=True, raw=False, data=None, headers=None):
    h = {'Content-Type': 'application/json'}
    if hdr: h['X-Requested-With'] = 'rax'
    h.update(headers or {})
    payload = data if data is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(BASE + path, data=payload, method=method, headers=h)
    try:
        with opener.open(req, timeout=60) as r:
            b = r.read()
            return r.status, (b if raw == 'bytes' else b.decode() if raw else json.loads(b.decode()))
    except urllib.error.HTTPError as e:
        b = e.read().decode() or '{}'
        try:
            return e.code, json.loads(b)
        except ValueError:
            return e.code, b


def wait_idle(timeout=60):
    t = time.time()
    while time.time() - t < timeout:
        _, j = call('GET', '/api/jobs'); _, s = call('GET', '/api/searches')
        busy = [x for x in j if x['status'] == 'running'] + [x for x in s if x['status'] in ('queued', 'running')]
        if not busy:
            time.sleep(0.4)
            _, j = call('GET', '/api/jobs'); _, s = call('GET', '/api/searches')
            if not [x for x in j if x['status'] == 'running'] + [x for x in s if x['status'] in ('queued', 'running')]:
                return True
        time.sleep(0.3)
    return False


def lead_by(name):
    return next((l for l in call('GET', '/api/leads?per=500')[1]['rows'] if l['company'] == name), {})


print('1. Page, files and settings')
s, r = call('GET', '/', raw=True); check(s == 200 and '<title>RAX Surgicals Outreach</title>' in r, 'dashboard page loads')
check('Find buyers. Email them. Turn replies into orders.' in r and r.count('RAX Surgicals Outreach') >= 4, 'the new name and the slogan are on the page')
s, me = call('GET', '/api/me')
check(me.get('app') == 'RAX Outreach' and me.get('name') == 'RAX Surgicals Outreach' and me.get('version') == '2.2',
      'the app answers with its new name, and with the old one that setup and the launcher look for', me)
for path, want in [('/js/app.js', 'text/javascript'), ('/css/app.css', 'text/css'), ('/fonts/atkinson-hyperlegible-next.woff2', 'font/woff2')]:
    req = urllib.request.Request(BASE + path, method='HEAD')
    with opener.open(req) as resp:
        check(resp.headers.get('Content-Type', '').startswith(want), f'{path} served as {want} (works on Windows too)', resp.headers.get('Content-Type'))
s, r = call('GET', '/js/nope.js', raw=True); check(s == 404, 'missing file gives 404, not the page')
s, me = call('GET', '/api/me'); check(me['logged_in'] and not me['auth_required'] and me['version'] == db.VERSION and me['lang'] == 'en' and not me['setup_done'],
                                      'me: no login on own PC, version, English, setup not done', me)
s, r = call('POST', '/api/settings', {'anthropic_api_key': 'sk-test', 'google_places_api_key': 'places-test', 'sender_name': 'Rohail Ahmed', 'sender_title': 'Export Manager',
                                      'sender_email': 'sales@raxsurgicals.test', 'smtp_host': '127.0.0.1', 'smtp_port': str(M['smtp'].server_address[1]),
                                      'smtp_security': 'none', 'smtp_user': 'sales@raxsurgicals.test', 'smtp_password': 'smtp-pass', 'imap_host': 'fake',
                                      'send_hour_start': '0', 'send_hour_end': '24', 'send_weekdays_only': '0', 'gap_min_minutes': '0', 'gap_max_minutes': '0',
                                      'company_website': 'https://raxsurgicals.com', 'warmup_on': '0', 'daily_limit': '999', 'bogus_key': 'x', 'save_sent_copy': 'on'})
check(s == 200 and r['anthropic_api_key'].startswith('•') and r['anthropic_api_key'].endswith('test'), 'secret keys are masked when read back', r)
check('bogus_key' not in r and r['daily_limit'] == '200', 'unknown settings ignored, daily limit capped at 200', r.get('daily_limit'))
s, r = call('POST', '/api/settings', {'reply_to': 'not an email'}); check(s == 400 and r.get('code') == 'bad_email', 'bad reply-to address refused with a code', r)
call('POST', '/api/settings', {'anthropic_api_key': '••••••••test', 'daily_limit': '50'})
check(db.get('anthropic_api_key') == 'sk-test', 'saving the masked value keeps the real key')
s, r = call('POST', '/api/settings', {'x': 1}, hdr=False); check(s == 400, 'POST without the dashboard header is refused')
conn = http.client.HTTPConnection('127.0.0.1', PORT, timeout=10)      # keep-alive: a refused POST must not break the next request
conn.request('POST', '/api/settings', body=json.dumps({'daily_limit': 5}), headers={'Content-Type': 'application/json'}); r1 = conn.getresponse(); r1.read()
conn.request('GET', '/api/me'); r2 = conn.getresponse(); b2 = r2.read()
check(r1.status == 400 and r2.status == 200 and b'version' in b2, 'kept-alive connection still works after a refused request', (r1.status, r2.status))
conn.close()
mailer._imap = lambda: mocks.FakeIMAP()

print('2. Tests in settings (with plain-word error codes)')
mocks.SENT.clear()
s, r = call('POST', '/api/test/ai', {}); check(s == 200 and 'Hello' in r['said'], 'AI test works', r)
db.put('anthropic_api_key', 'sk-bad'); s, r = call('POST', '/api/test/ai', {}); db.put('anthropic_api_key', 'sk-test')
check(s == 400 and r.get('code') == 'ai_bad_key', 'wrong AI key explained (code ai_bad_key)', r)
s, r = call('POST', '/api/test/smtp', {'to': 'me@raxsurgicals.test'}); check(s == 200 and len(mocks.SENT) == 1, 'SMTP test email sent', r)
db.put('smtp_password', 'wrong'); s, r = call('POST', '/api/test/smtp', {'to': 'me@raxsurgicals.test'}); db.put('smtp_password', 'smtp-pass')
check(s == 400 and r.get('code') == 'auth_failed', 'wrong mailbox password explained (code auth_failed)', r)
db.put('smtp_host', 'smtp.gmail.com.invalid'); s, r = call('POST', '/api/test/smtp', {'to': 'me@raxsurgicals.test'}); db.put('smtp_host', '127.0.0.1')
check(s == 400 and r.get('code') == 'host_not_found', 'unknown server name explained (code host_not_found)', r)
s, r = call('POST', '/api/test/places', {}); check(s == 200 and r['found'] == 1, 'Google key test', r)
db.put('google_places_api_key', 'bad'); s, r = call('POST', '/api/test/places', {}); db.put('google_places_api_key', 'places-test')
check(s == 400 and r.get('code') == 'places_bad_key', 'wrong Google key explained', r)
s, r = call('GET', '/api/check/domain')
codes = {i['key']: i['code'] for i in r.get('items', [])}
check(codes == {'mx': 'mx_ok', 'spf': 'spf_ok', 'dmarc': 'dmarc_missing', 'dkim': 'dkim_ok'}, 'own domain check: MX, SPF, DKIM found, DMARC missing', r)
db.put('sender_email', 'someone@gmail.com'); s, r = call('GET', '/api/check/domain'); db.put('sender_email', 'sales@raxsurgicals.test')
check(r.get('free') and r['items'][0]['code'] == 'free_mailbox', 'free Gmail address flagged for cold email', r)

print('3. Google Maps search queue (two places), reading websites, email checks')
s, r = call('POST', '/api/search', {'query': 'surgical instruments distributor', 'locations': 'Germany\nMunich, Germany', 'max': 60, 'auto_check': True})
check(s == 200 and r['queued'] == 2, 'two searches queued', r)
check(wait_idle(), 'searches and checks finished')
s, S = call('GET', '/api/searches')
check(len(S) == 2 and all(x['status'] == 'done' for x in S) and S[-1]['added'] == 4 and S[0]['added'] == 0, 'history: first search added 4, second found only duplicates', S)
L = {l['company']: l for l in call('GET', '/api/leads?per=500')[1]['rows']}
check(set(L) == {'MedSupply GmbH', 'DentalHaus', 'Sialkot Makers', 'No Web Clinic Supplies'}, 'closed business skipped, 4 leads', list(L))
ms = L['MedSupply GmbH']
check(ms['email'] == 'purchasing@medsupply.test' and ms['email_status'] == 'valid', 'best email picked and its domain takes email', ms)
full = call('GET', f"/api/leads/{ms['id']}")[1]
check(set(full['emails']) == {'purchasing@medsupply.test', 'sales@medsupply.test', 'info@medsupply.test'}, 'jobs@, image names and tracker emails filtered', full['emails'])
check(ms['fit'] == 'good' and ms['status'] == 'ready' and full['contact_name'] == 'Anna Keller', 'AI: good fit, ready, contact name found', ms)
check(full['timeline'] and full['timeline'][-1]['type'] == 'found', 'lead timeline starts with "found"', full['timeline'][-1:])
dh = L['DentalHaus']; dfull = call('GET', f"/api/leads/{dh['id']}")[1]
check(dh['email'] == 'kontakt@dentalhaus.test' and 'secret@dentalhaus.test' not in dfull['emails'] and dfull['language'] == 'de', '"[at] [dot]" email found; robots.txt respected; language', dfull['emails'])
check(L['Sialkot Makers']['fit'] == 'no' and L['Sialkot Makers']['status'] == 'rejected', 'competitor in Sialkot rejected')
nw = L['No Web Clinic Supplies']
check(nw['crawl_status'] == 'no_website' and nw['status'] == 'new' and nw['fit'] == 'maybe', 'no website: kept as new, never "good" on the name alone', nw)
check(len(mocks.PLACES_CALLS) >= 4 and db.q("SELECT COUNT(*) n FROM usage WHERE kind='places'", one=True)['n'] >= 4, 'Google requests counted for the cost view')
s, r = call('POST', '/api/search/suggest', {'location': 'Germany'}); check(r['by'] == 'ai' and 'Medizinischer Großhandel' in r['queries'], 'AI search ideas', r)
db.put('anthropic_api_key', ''); s, r = call('POST', '/api/search/suggest', {'location': 'Hamburg, Germany'}); db.put('anthropic_api_key', 'sk-test')
check(r['by'] == 'list' and 'Praxisbedarf' in r['queries'] and 'surgical instruments distributor' in r['queries'], 'search ideas without AI: German + English', r)

print('4. Pasted list, Excel and CSV import')
s, r = call('POST', '/api/leads/paste', {'text': f"{url('pasted-one.test')}\nbuyer@nomail.test, nonsense\nmedsupply.test\nfoo@gmail.com", 'country': 'France'})
check(s == 200 and r['added'] == 3 and r['skipped'] == 2, 'pasted: 1 website + 2 emails added; junk and duplicate skipped', r)
wait_idle()
p1 = lead_by('Pasted One Medical')
check(p1.get('email') == 'orders@pasted-one.test' and p1.get('country') == 'France', 'company name taken from the website, email found', p1)
nm = next((l for l in call('GET', '/api/leads?q=nomail')[1]['rows']), {})
check(nm.get('email_status') == 'no_mx' and nm.get('status') == 'new', 'email at a domain with no mail server marked no_mx and not ready', nm)
gm = next((l for l in call('GET', '/api/leads?q=foo@gmail')[1]['rows']), {})
check(gm.get('email_status') == 'free' and gm.get('website') == '', 'gmail address: free mailbox, no website guessed', gm)
from openpyxl import Workbook
wb = Workbook(); ws = wb.active
ws.append(['Firma', 'Webseite', 'E-Mail', 'Land', 'Ansprechpartner'])
ws.append(['XLSX Co', 'xlsxco.test', 'einkauf@xlsxco.test; info@xlsxco.test', 'Austria', 'Eva Gruber'])
ws.append(['MedSupply GmbH', 'www.medsupply.test', '', 'Germany', ''])
ws.append([None, None, None, None, None])
ws.append(['Phone Only Co', None, None, 'Spain', None])
buf = io.BytesIO(); wb.save(buf); xb64 = base64.b64encode(buf.getvalue()).decode()
s, pv = call('POST', '/api/import/preview', {'name': 'fair.xlsx', 'data': xb64})
check(s == 200 and pv['headers'][:3] == ['Firma', 'Webseite', 'E-Mail'] and pv['rows'] == 3 and pv['mapping'] == {'company': 0, 'website': 1, 'email': 2, 'country': 3, 'contact_name': 4},
      'Excel preview: German column names recognised', pv)
s, r = call('POST', '/api/import/commit', {'name': 'fair.xlsx', 'data': xb64, 'mapping': pv['mapping'], 'auto_check': False})
check(r.get('added') == 2 and r.get('skipped') == 1, 'Excel import: 2 added, 1 duplicate', r)
xl = lead_by('XLSX Co'); check(xl.get('email') == 'einkauf@xlsxco.test' and xl.get('contact_name') == 'Eva Gruber', 'first email of "a; b" cell used', xl)
s, r = call('POST', '/api/import/preview', {'name': 'old.xls', 'data': base64.b64encode(b'\xd0\xcf\x11\xe0').decode()})
check(s == 400 and r.get('code') == 'old_excel', 'old .xls explained (save as .xlsx)', r)
csv_text = 'Company;Website;E-mail;Country;Contact\nMedSupply again;medsupply.test;;Germany;\nCSV Co;' + url('csvco.test') + ';buyer@csvco.test;;Sam Lee\n'
s, r = call('POST', '/api/leads/import', {'csv': csv_text, 'country': 'United Kingdom'})
check(r == {'added': 1, 'skipped': 1}, 'CSV import (version 1 style) still works', r)
call('POST', '/api/leads/check', {}); wait_idle()
cc = lead_by('CSV Co'); check(cc.get('status') == 'ready' and cc.get('country') == 'United Kingdom', 'CSV lead checked and ready', cc)
s, csvout = call('GET', '/api/leads/export.csv', raw=True); check(s == 200 and csvout.startswith('﻿company,website,email,email_status') and 'MedSupply' in csvout, 'export CSV (opens right in Excel)')
s, r = call('GET', '/api/leads?view=bad_email'); check(r['total'] == 1 and r['counts']['ready'] >= 3, 'quick views with counts', r['counts'])

print('5. Campaign, quality checks, approval, sending')
steps = [{'day': 0, 'kind': 'ai', 'instructions': 'Offer catalogue'}, {'day': 4, 'kind': 'ai', 'instructions': 'Private label'},
         {'day': 9, 'kind': 'template', 'body': 'Hi {first_name},\n\nLast note from {my_name} at {my_company}. Samples?', 'subject': ''}]
s, r = call('POST', '/api/campaigns/0/preview', {'draft': {'name': 'x', 'steps': steps}, 'step': 0})
check(s == 200 and r['written_by'] == 'ai' and 'unsubscribe' in r['footer'] and isinstance(r['lint'], list), 'preview of an unsaved campaign', r)
s, c = call('POST', '/api/campaigns', {'name': 'Distributors', 'pitch': 'Instruments and private label', 'steps': steps}); cid = c['id']
s, r = call('POST', f'/api/campaigns/{cid}/enroll', {'ids': [nm['id']]})
check(r['added'] == 0 and r['skipped'][0]['why'] == 'no_mail_server', 'lead whose domain takes no email is not added', r)
s, r = call('POST', f'/api/campaigns/{cid}/enroll', {'all_ready': True})
added = r['added']; check(added >= 5, 'ready leads added', r)
time.sleep(0.5); worker.draft_tick(20)
s, D = call('GET', '/api/messages?status=draft')
check(len(D['rows']) == added and all(m['written_by'] == 'ai' and m['steps_total'] == 3 and 'lint' in m for m in D['rows']), 'AI drafts with quality checks', len(D['rows']))
d_ms = next(m for m in D['rows'] if m['company'] == 'MedSupply GmbH')
s, r = call('PATCH', f"/api/messages/{d_ms['id']}", {'subject': 'Instruments for MedSupply', 'body': 'Hello {first_name},\n\nFREE samples!!! Click here: http://a.test and www.b.test'})
codes = {f['code'] for f in r['lint']}
check({'placeholder', 'spam_words', 'many_links', 'exclaim'} <= codes, 'quality check finds placeholder, spam words, links, exclamation marks', codes)
s, r = call('POST', '/api/messages/approve', {'ids': [d_ms['id']]}); check(r == {'approved': 0, 'blocked': [d_ms['id']]}, 'email with a leftover placeholder cannot be approved', r)
s, r = call('PATCH', f"/api/messages/{d_ms['id']}", {'subject': 'Instruments for MedSupply', 'body': 'Hello Anna,\n\nEdited by me. Would MedSupply like our catalogue?'})
check(not quality.blocks(r['lint']), 'fixed email passes', r['lint'])
mocks.SENT.clear()
s, r = call('POST', f"/api/messages/{d_ms['id']}/test", {}); check(s == 200 and r['to'] == 'sales@raxsurgicals.test' and len(mocks.SENT) == 1, 'send a test copy to myself', r)
tm = email.message_from_bytes(mocks.SENT[0]['raw'], policy=email.policy.default); check(tm['Subject'].startswith('[Test]'), 'test copy marked [Test]')
check(db.q('SELECT status FROM messages WHERE id=?', (d_ms['id'],), one=True)['status'] == 'draft', 'test send does not send the real email')
others = [m['id'] for m in D['rows'] if m['id'] != d_ms['id']]
s, r = call('POST', '/api/messages/approve', {'ids': [d_ms['id']] + others}); check(r['approved'] == added, 'all approved', r)
mocks.SENT.clear(); mocks.FakeIMAP.APPENDED.clear()
db.put('warmup_on', '1'); db.put('warmup_start', '2'); db.put('warmup_step', '5'); db.put('warmup_started', dt.date.today().isoformat())
lim = worker.effective_limit(); check(lim == {'limit': 2, 'warmup': True, 'week': 1, 'full': 50}, 'warm-up: week 1 allows 2 a day', lim)
db.put('next_send_at', ''); r1 = worker.send_tick(); db.put('next_send_at', ''); r2 = worker.send_tick(); db.put('next_send_at', ''); r3 = worker.send_tick()
check((r1, r2, r3) == ('sent', 'sent', 'daily limit reached'), 'warm-up limit stops the third email today', (r1, r2, r3))
db.put('warmup_started', (dt.date.today() - dt.timedelta(days=15)).isoformat())
check(worker.effective_limit()['limit'] == 12, 'week 3 of warm-up allows 2 + 5 + 5 = 12')
db.put('warmup_on', '0')
while worker.send_tick(force_now=True) == 'sent': pass
check(len(mocks.SENT) == added, 'all approved emails sent', len(mocks.SENT))
time.sleep(0.5)
check(len(mocks.FakeIMAP.APPENDED) == added and mocks.FakeIMAP.APPENDED[0][0] == '"Sent Items"', 'a copy of each sent email saved in the Sent folder', [a[0] for a in mocks.FakeIMAP.APPENDED][:2])
m1 = email.message_from_bytes(next(x['raw'] for x in mocks.SENT if b'Edited by me' in x['raw']), policy=email.policy.default)
b1 = m1.get_content()
check(m1['To'] == 'purchasing@medsupply.test' and 'Rohail Ahmed' in m1['From'] and 'Sialkot, Punjab, Pakistan' in b1 and 'reply "unsubscribe"' in b1 and m1['List-Unsubscribe'],
      'headers, signature, address, unsubscribe line', (m1['To'], m1['From']))
fc = worker.forecast(); check('countries' in fc, 'forecast available')

print('6. Replies, answering with an attachment, forwarding, pipeline')
first_mid = db.q("SELECT message_id FROM messages WHERE lead_id=? AND status='sent'", (ms['id'],), one=True)['message_id']
their = make_msgid()
r1 = (f"From: Anna Keller <anna@medsupply.test>\r\nTo: sales@raxsurgicals.test\r\nSubject: Re: Instruments for MedSupply\r\n"
      f"Message-ID: {their}\r\nIn-Reply-To: {first_mid}\r\nContent-Type: text/plain\r\n\r\nPlease send your price list.\r\n\r\nOn Mon, Rohail wrote:\r\n> Hello Anna\r\n").encode()
r2 = (f"From: Mail Delivery Subsystem <mailer-daemon@googlemail.com>\r\nSubject: Delivery Status Notification (Failure)\r\nMessage-ID: {make_msgid()}\r\n"
      f"Content-Type: text/plain\r\n\r\nYour message wasn't delivered to kontakt@dentalhaus.test because the address couldn't be found.\r\n").encode()
mocks.FakeIMAP.INBOX = [r1, r2]
db.put('forward_on', '1'); db.put('forward_to', 'boss@raxsurgicals.test'); db.put('forward_kinds', 'interested,question')
mocks.SENT.clear()
res = mailer.check_replies(); check(res['new'] == 2, 'reply and bounce recorded', res)
fwd = [email.message_from_bytes(x['raw'], policy=email.policy.default) for x in mocks.SENT]
check(len(fwd) == 1 and fwd[0]['To'] == 'boss@raxsurgicals.test' and fwd[0]['Subject'].startswith('Fwd:') and 'price list' in fwd[0].get_content(),
      'interested reply forwarded by itself', [f['To'] for f in fwd])
s, ib = call('GET', '/api/inbox'); check(ib['counts']['needs'] == 1 and ib['rows'][0]['company'] == 'MedSupply GmbH', 'inbox: one conversation needs an answer', ib)
s, th = call('GET', f"/api/inbox/{ms['id']}")
check([i['who'] for i in th['items']] == ['us', 'them', 'fwd'] and th['subject'] == 'Re: Instruments for MedSupply' and th['answer_to'],
      'thread: our email, their reply, the forward', [i['who'] for i in th['items']])
check(db.q('SELECT stage FROM leads WHERE id=?', (ms['id'],), one=True)['stage'] == 'interested', 'interested reply puts the lead in the pipeline')
s, dr = call('POST', f"/api/inbox/{ms['id']}/draft", {'reply_id': th['answer_to'], 'note': 'mention MOQ'})
check(s == 200 and dr['by'] == 'ai' and 'price list' in dr['body'] and 'mention MOQ' in mocks.AI_CALLS[-1]['user'], 'AI writes the answer, with my note', dr)
pdf = b'%PDF-1.4 test catalogue'
s, f = call('POST', '/api/files', data=pdf, headers={'Content-Type': 'application/pdf', 'X-File-Name': 'RAX%20Catalogue.pdf'}); fid = f['id']
s, fl = call('GET', '/api/files'); check(fl[0]['name'] == 'RAX Catalogue.pdf' and fl[0]['size'] == len(pdf), 'catalogue uploaded to the file library', fl)
s, r = call('POST', f"/api/inbox/{ms['id']}/send", {'subject': th['subject'], 'body': 'Hello [Name],', 'reply_id': th['answer_to']})
check(s == 400 and r.get('code') == 'blocked', 'answer with a placeholder is held back', r)
mocks.SENT.clear()
s, r = call('POST', f"/api/inbox/{ms['id']}/send", {'subject': th['subject'], 'body': dr['body'], 'reply_id': th['answer_to'], 'file_ids': [fid], 'stage': 'quote'})
check(s == 200, 'answer sent', r)
am = email.message_from_bytes(mocks.SENT[0]['raw'], policy=email.policy.default)
atts = [p for p in am.iter_attachments()]
check(am['To'] == 'anna@medsupply.test' and am['In-Reply-To'] == their and first_mid in am['References'] and atts and atts[0].get_filename() == 'RAX Catalogue.pdf'
      and atts[0].get_content() == pdf, 'answer: to the person who wrote, same thread, catalogue attached', (am['To'], am['In-Reply-To'], am['References']))
check('unsubscribe' not in am.get_body(('plain',)).get_content(), 'answers carry no unsubscribe line')
check(call('GET', '/api/inbox')[1]['counts']['needs'] == 0 and db.q('SELECT stage FROM leads WHERE id=?', (ms['id'],), one=True)['stage'] == 'quote',
      'answered: inbox clear, stage moved to quote')
other = db.q("SELECT message_id, lead_id, to_email, subject FROM messages WHERE status='sent' AND lead_id<>? AND to_email<>'kontakt@dentalhaus.test' ORDER BY id LIMIT 1",
             (ms['id'],), one=True)
r3 = (f"From: {other['to_email']}\r\nSubject: Re: {other['subject']}\r\nMessage-ID: {make_msgid()}\r\nIn-Reply-To: {other['message_id']}\r\n"
      "Content-Type: text/plain\r\n\r\nThanks, we are not interested at the moment.\r\n").encode()
mocks.FakeIMAP.INBOX = [r3]
mailer.check_replies()
s, ib = call('GET', '/api/inbox'); s, closed = call('GET', '/api/inbox?f=bounces')
check(ib['counts']['needs'] == 0 and any(c['lead_id'] == other['lead_id'] for c in closed['rows'])
      and db.q('SELECT status FROM leads WHERE id=?', (other['lead_id'],), one=True)['status'] == 'not_interested',
      'a "not interested" reply needs no answer and is listed under Closed', ib['counts'])
tday = dt.date.today().isoformat()
s, r = call('PATCH', f"/api/leads/{ms['id']}/deal", {'deal_value': '2,500', 'next_action': 'Send samples', 'next_action_date': tday})
s, r = call('PATCH', f"/api/leads/{ms['id']}/deal", {'next_action_date': '20-10-2026'}); check(s == 400 and r.get('code') == 'bad_date', 'bad date refused')
s, pl = call('GET', '/api/pipeline')
quote = next(c for c in pl['stages'] if c['stage'] == 'quote')
check(quote['value'] == 2500 and quote['leads'][0]['next_action'] == 'Send samples', 'pipeline: quote column with value and next step', quote)
s, r = call('POST', f"/api/leads/{ms['id']}/notes", {'text': 'Called Anna, wants 200 needle holders'})
lf = call('GET', f"/api/leads/{ms['id']}")[1]
types = [e['type'] for e in lf['timeline']]
check({'found', 'sent', 'reply', 'answered', 'stage', 'note', 'forwarded'} <= set(types), 'timeline shows the whole story', types)
s, b = call('GET', '/api/badges'); check(b['tasks'] == 1 and b['inbox'] == 0 and b['last_reply']['kind'] == 'interested', 'badges: one task due today', b)
check(db.suppressed('kontakt@dentalhaus.test') and db.q('SELECT status FROM leads WHERE id=?', (dh['id'],), one=True)['status'] == 'bounced', 'bounce: lead stopped, address blocked')

print('7. Bounce protection, sending at office hours, today and reports')
db.put('sending_paused', '0'); db.put('bounce_guard_pct', '5')
fake_ids = []
for i in range(25):
    lid = finder.add_lead({'company': f'Bulk {i}', 'email': f'b{i}@limit.test', 'country': 'Japan'}, 'manual')
    db.x("INSERT INTO messages(lead_id, step, to_email, subject, body, status, kind, sent_at, message_id) VALUES (?,0,?,?,?,'sent','campaign',?,?)",
         (lid, f'b{i}@limit.test', 's', 'b', db.now(), make_msgid()))
    fake_ids.append(lid)
for lid in fake_ids[:3]:
    db.x("INSERT INTO replies(lead_id, from_email, subject, body, kind, summary, received_at, msg_key) VALUES (?,?,?,?,?,?,?,?)",
         (lid, 'mailer-daemon@x', 'fail', 'x', 'bounce', 's', db.now(), make_msgid()))
check(worker.bounce_guard() and db.get('sending_paused') == '1' and db.get('paused_reason') == 'bounces', 'too many bounces: sending paused by itself')
s, r = call('POST', '/api/sending', {'paused': False}); check(db.get('paused_reason') == '' and db.get('sending_paused') == '0', 'resume clears the pause')
db.put('bounce_guard_pct', '50')
db.put('send_hour_start', '9'); db.put('send_hour_end', '17'); db.put('send_weekdays_only', '1')
sat = dt.datetime(2026, 10, 10, 12, 0, tzinfo=dt.timezone.utc)
check(not worker.in_office_hours('Germany', sat), 'weekend skipped')
mon1 = dt.datetime(2026, 10, 12, 1, 0, tzinfo=dt.timezone.utc)
check(worker.in_office_hours('Japan', mon1) and not worker.in_office_hours('Germany', mon1), 'office hours use the recipient country time zone')
nxt = worker.next_open('Germany', mon1); check(nxt and nxt.astimezone(worker.tz_for('Germany')).hour == 9, 'next office hour in Germany found', nxt)
db.put('send_hour_start', '0'); db.put('send_hour_end', '24'); db.put('send_weekdays_only', '0')
s, t = call('GET', '/api/today')
check(len(t['series']) == 14 and t['week']['sent'] >= added and t['counts']['inbox'] == 0 and t['pipeline']['quote']['value'] == 2500 and t['tasks'],
      'today: chart data, counts, pipeline and tasks', {k: t[k] for k in ('week', 'counts')})
check(t['usage']['ai_calls'] > 0 and t['usage']['ai_cost'] >= 0 and t['setup']['email'] and t['setup']['ai'], 'today: AI use and setup state', t['usage'])
s, rp = call('GET', '/api/reports?days=30')
check(rp['funnel']['contacted'] >= added and rp['funnel']['interested'] == 1 and rp['by_country'] and rp['campaigns'][0]['sent'] >= added, 'reports: funnel, countries, campaigns', rp['funnel'])

print('8. Backup and restore')
s, data = call('GET', '/api/backup', raw='bytes'); check(s == 200 and data.startswith(b'SQLite format 3'), 'backup download is a database file')
db.put('company_name', 'Changed Name')
s, r = call('POST', '/api/restore', data=data, headers={'Content-Type': 'application/octet-stream'}); check(s == 200, 'restore accepted', r)
check(db.get('company_name') == 'RAX Surgicals', 'restore brought the old data back')
s, r = call('POST', '/api/restore', data=b'not a database', headers={'Content-Type': 'application/octet-stream'}); check(s == 400 and r.get('code') == 'bad_backup', 'wrong file refused')
s, r = call('GET', '/api/backups'); check(any(f['name'].startswith('before-restore') for f in r['files']), 'a safety copy is kept before restoring')

print('9. Version 1 data opens in version 2')
v1dir = tempfile.mkdtemp(prefix='raxv1-')
V1 = os.path.join(os.path.dirname(ROOT), 'outreach_v1')
subprocess.run([sys.executable, '-c', '''
import sys; sys.path.insert(0, sys.argv[1])
from app import db; db.init()
db.put("smtp_host", "smtp.zoho.com"); db.put("sender_email", "a@b.test")
lid = db.x("INSERT INTO leads(company, email, status, created_at) VALUES ('Old Co', 'x@old.test', 'replied', '2026-10-01T00:00:00+00:00')")
db.x("INSERT INTO messages(lead_id, step, to_email, subject, body, status, sent_at, message_id) VALUES (?,0,'x@old.test','Hi','Body','sent','2026-10-01T00:00:00+00:00','<a@b>')", (lid,))
db.x("INSERT INTO replies(lead_id, from_email, subject, body, kind, summary, received_at, msg_key) VALUES (?,'x@old.test','Re: Hi','yes','interested','s','2026-10-02T00:00:00+00:00','<their@x>')", (lid,))
''', V1], env={**os.environ, 'RAX_DATA_DIR': v1dir}, check=True)
out = subprocess.run([sys.executable, '-c', '''
import sys, json; sys.path.insert(0, sys.argv[1])
from app import db; db.init()
cols = {r["name"] for r in db.q("PRAGMA table_info(leads)")}
print(json.dumps({"stage": "stage" in cols, "kind": db.q("SELECT kind FROM messages", one=True)["kind"], "setup": db.get("setup_done"),
                  "mid": db.q("SELECT message_id FROM replies", one=True)["message_id"], "warm": db.get("warmup_on")}))
''', ROOT], env={**os.environ, 'RAX_DATA_DIR': v1dir}, capture_output=True, text=True)
try:
    mig = json.loads(out.stdout.strip().splitlines()[-1])
except Exception:
    mig = {'error': out.stderr[-800:]}
check(mig == {'stage': True, 'kind': 'campaign', 'setup': '1', 'mid': '<their@x>', 'warm': '1'}, 'v1 database upgraded: new columns, settings kept, wizard skipped', mig)
pre = [f for f in os.listdir(os.path.join(v1dir, 'backups')) if f.startswith('before-2.2-')] if os.path.isdir(os.path.join(v1dir, 'backups')) else []
check(len(pre) == 1 and 'stage' not in {r[1] for r in sqlite3.connect(os.path.join(v1dir, 'backups', pre[0])).execute('PRAGMA table_info(leads)')},
      'a copy of the version 1 data is kept before upgrading', pre)

print('10. Password, server mode, stopping')
s, r = call('POST', '/api/settings/password', {'password': 'short'}); check(s == 400 and r.get('code') == 'pw_short', 'short password refused')
s, r = call('POST', '/api/settings/password', {'password': 'raxsecret123'}); check(s == 200, 'password set')
jar.clear()
s, r = call('GET', '/api/today'); check(s == 401 and r.get('code') == 'login', 'API locked after password set')
s, r = call('GET', '/api/backup', raw='bytes'); check(s == 401, 'backup download locked too')
s, r = call('POST', '/api/login', {'password': 'nope'}); check(s == 401 and r.get('code') == 'pw_wrong', 'wrong password refused')
s, r = call('POST', '/api/login', {'password': 'raxsecret123'}); check(s == 200, 'login')
s, st = call('GET', '/api/settings'); check('admin_password_hash' not in st and st['password_set'], 'password hash never sent to the page')
errs = db.q("SELECT text FROM log WHERE level='error' AND text NOT LIKE 'Sending paused%' AND text NOT LIKE 'Google Maps search failed%'")
check(not errs, 'no unexpected errors in the log', errs)
s, au = call('GET', '/api/autostart'); check(s == 200 and au == {'supported': False, 'on': False}, 'start with Windows only offered in the installed Windows app', au)
s, r = call('POST', '/api/autostart', {'on': True}); check(s == 400 and r.get('code') == 'autostart', 'turning it on elsewhere is refused', r)
jar.clear()
s, r = call('POST', '/api/shutdown', {}, headers={'X-RAX-Stop': 'wrong-token'}); check(s == 401, 'a wrong stop token does not stop the app', (s, r))
tok = open(os.path.join(db.DATA_DIR, 'stop.token')).read().strip()
check(len(tok) == 32, 'the app leaves a stop token for the installer in its data folder')
s, r = call('POST', '/api/login', {'password': 'raxsecret123'})
s, r = call('POST', '/api/shutdown', {}); time.sleep(1.2)
try:
    urllib.request.build_opener(urllib.request.ProxyHandler({})).open(BASE + '/api/me', timeout=2); stopped = False
except Exception:
    stopped = True
check(s == 200 and stopped, 'stop button stops the software')

print('11. The dashboard window: its own clean browser profile')
import importlib.util
spec = importlib.util.spec_from_file_location('rax_start', os.path.join(ROOT, 'start.py'))
start = importlib.util.module_from_spec(spec); spec.loader.exec_module(start)
os.environ['LOCALAPPDATA'] = os.path.join(TMP, 'LocalAppData')
prof = start.window_profile()
check(prof == os.path.join(TMP, 'LocalAppData', 'RAX Surgicals Outreach', 'window'), 'window profile sits in its own folder, not in the normal browser', prof)
os.environ['RAX_WINDOW_PROFILE'] = os.path.join(TMP, 'from-launcher', 'window')
check(start.window_profile() == os.path.join(TMP, 'from-launcher', 'window'), 'the installed app uses the profile its launcher names')
del os.environ['RAX_WINDOW_PROFILE']
a = start.window_args('http://127.0.0.1:8765/', prof)
check(a[0] == '--app=http://127.0.0.1:8765/' and f'--user-data-dir={prof}' in a and {'--no-first-run', '--disable-extensions', '--disable-sync',
      '--disable-features=Translate', '--no-default-browser-check'} <= set(a) and '--window-size=1360,880' in a, 'first opening: app mode, no extensions, no translate bar, a size', a)
os.makedirs(prof, exist_ok=True)
check(not [x for x in start.window_args('http://127.0.0.1:8765/', prof) if x.startswith('--window-')], 'later openings keep the size the user chose')
rec = os.path.join(TMP, 'browser-args.txt')
fake = os.path.join(TMP, 'fake-browser.sh')
open(fake, 'w').write('#!/bin/sh\nfor a in "$@"; do echo "$a"; done > ' + rec + '\n'); os.chmod(fake, 0o755)
start.app_browsers = lambda: [fake]
start.open_window('http://127.0.0.1:8765/')
time.sleep(0.8)
got = open(rec).read().split('\n') if os.path.exists(rec) else []
check(f'--user-data-dir={prof}' in got and '--app=http://127.0.0.1:8765/' in got, 'the browser is started with those options', got)
page = open(os.path.join(ROOT, 'app', 'static', 'index.html'), encoding='utf-8').read()
check('translate="no"' in page and 'name="google" content="notranslate"' in page, 'the page asks browsers not to offer translation')
print(f'\n{ok} passed, {fail} failed')
sys.exit(1 if fail else 0)
